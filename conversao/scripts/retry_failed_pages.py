#!/usr/bin/env python3
"""
DocMind Retry Failed Pages
Scans validation files for failed pages and retries them once.

Features:
- Skips DataInspectionFailed (content moderation) - will fail again
- Retries NoneType/timeout/network errors
- Updates chunk .md files in place
- Generates retry_failures.yaml for permanent failures
- Integrates with quality report "Manual Review Required" section
"""

import sys
import os
import re
import yaml
import json
import time
import base64
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from io import BytesIO

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from config import AppConfig

APP_CONFIG = AppConfig.from_env()

# Try to import from docmind_converter
try:
    from docmind_converter import (
        DEFAULT_CONTEXT_MODE, DEFAULT_PROMPT_MODE,
        DEFAULT_RETRY_CONFIG, ContextMode, PromptMode,
        build_context_window, build_prompt, safe_get_text_from_response,
        APIKeyHealthMonitor, _api_key_monitor
    )
    DOCMIND_AVAILABLE = True
except ImportError:
    DOCMIND_AVAILABLE = False

# Phase 3 LLM model — see ADR-0001 / Phase C. Default lives in AppConfig
# (env var DOCMIND_LLM_MODEL overrides). Kept as module name for backwards
# compat with --model CLI default.
DEFAULT_MODEL = APP_CONFIG.llm_model

# ============ Configuration ============

# Error types that should NOT be retried (will fail again)
SKIP_ERROR_PATTERNS = [
    "DataInspectionFailed",      # Content moderation - political content
    "inappropriate content",      # Same as above
    "InvalidParameter",          # Bad request format
    "InvalidAPIKey",             # Auth issues
]

# Error types that SHOULD be retried (transient errors)
RETRY_ERROR_PATTERNS = [
    "NoneType",                  # API returned None
    "TimeoutError",              # Network timeout
    "ConnectionError",           # Network issues
    "SSLError",                  # SSL issues
    "502", "503", "504",         # Server errors
    "UNEXPECTED_EOF",            # Connection dropped
    "Rate limit",                # Rate limiting (with backoff)
]


def should_retry_error(error_msg: str) -> Tuple[bool, str]:
    """
    Determine if an error should be retried.

    Returns: (should_retry, reason)
    """
    error_lower = error_msg.lower()

    # Check skip patterns first
    for pattern in SKIP_ERROR_PATTERNS:
        if pattern.lower() in error_lower:
            return False, f"Skip: {pattern} (will fail again)"

    # Check retry patterns
    for pattern in RETRY_ERROR_PATTERNS:
        if pattern.lower() in error_lower:
            return True, f"Retry: {pattern} (transient error)"

    # Default: retry unknown errors
    return True, "Retry: Unknown error type"


def load_api_keys(keys_file: Path) -> List[str]:
    """Load API keys from file."""
    keys = []
    if keys_file.exists():
        with open(keys_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    keys.append(line)
    return keys


def scan_validation_files(chunks_dir: Path) -> Dict[str, List[Dict]]:
    """
    Scan all validation.yaml files and collect failed pages.

    Returns: {chunk_name: [{page, error, image_path}, ...]}
    """
    failed_pages = {}

    for chunk_dir in chunks_dir.iterdir():
        if not chunk_dir.is_dir() or chunk_dir.name == "chunks":
            continue

        validation_file = chunk_dir / f"{chunk_dir.name}.validation.yaml"
        if not validation_file.exists():
            continue

        try:
            with open(validation_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                continue

            # Get failed pages
            failed_details = data.get('failed_pages_detail', [])
            if not failed_details:
                continue

            chunk_failures = []
            images_dir = chunk_dir / "images"

            for failure in failed_details:
                page_num = failure.get('page')
                error_msg = failure.get('error', 'Unknown error')

                # Check if image exists
                image_path = images_dir / f"page_{page_num:03d}.png"
                if not image_path.exists():
                    # Try alternate naming
                    image_path = images_dir / f"page_{page_num}.png"

                should_retry, reason = should_retry_error(error_msg)

                chunk_failures.append({
                    'page': page_num,
                    'error': error_msg,
                    'image_path': str(image_path) if image_path.exists() else None,
                    'should_retry': should_retry,
                    'reason': reason,
                    'chunk_dir': str(chunk_dir),
                    'chunk_name': chunk_dir.name
                })

            if chunk_failures:
                failed_pages[chunk_dir.name] = chunk_failures

        except Exception as e:
            print(f"  Warning: Could not parse {validation_file}: {e}")

    return failed_pages


def retry_single_page(
    page_info: Dict,
    api_keys: List[str],
    key_index: int,
    model: str = DEFAULT_MODEL
) -> Tuple[bool, str, int]:
    """
    Retry a single failed page.

    Returns: (success, result_or_error, new_key_index)
    """
    from dashscope import MultiModalConversation
    import dashscope
    from PIL import Image

    if not page_info.get('image_path') or not Path(page_info['image_path']).exists():
        return False, "Image file not found", key_index

    # Load image
    try:
        image = Image.open(page_info['image_path'])
    except Exception as e:
        return False, f"Failed to load image: {e}", key_index

    # Convert to base64
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

    # Build simple prompt (no context for retry)
    page_num = page_info['page']
    prompt = f"""### TASK: Convert this page image to structured Markdown

**Page Number**: {page_num}

**Instructions**:
1. Extract ALL text content from this page
2. Preserve paragraph structure and formatting
3. Convert tables to Markdown table format
4. Convert mathematical formulas to LaTeX ($ or $$)
5. Note any figures/charts with description
6. Keep original language (do NOT translate)

**Output Format** (JSON):
{{
  "page_number": {page_num},
  "has_figures": true/false,
  "figures": [],
  "tables": [],
  "formulas": [],
  "body_text": "...",
  "footnotes": []
}}

Return ONLY valid JSON."""

    messages = [
        {
            "role": "user",
            "content": [
                {"image": f"data:image/png;base64,{img_base64}"},
                {"text": prompt}
            ]
        }
    ]

    # Try with current API key
    api_key = api_keys[key_index % len(api_keys)]
    dashscope.api_key = api_key

    try:
        response = MultiModalConversation.call(
            model=model,
            messages=messages
        )

        if response.status_code == 200:
            # Extract text from response
            try:
                content = response.output.choices[0].message.content
                if isinstance(content, list):
                    text = content[0].get('text', '')
                else:
                    text = str(content)
                return True, text, (key_index + 1) % len(api_keys)
            except Exception as e:
                return False, f"Failed to parse response: {e}", (key_index + 1) % len(api_keys)
        else:
            error_msg = f"{response.code} - {response.message}"
            return False, error_msg, (key_index + 1) % len(api_keys)

    except Exception as e:
        return False, str(e), (key_index + 1) % len(api_keys)


def update_markdown_file(chunk_dir: Path, page_num: int, new_content: str) -> bool:
    """
    Update the chunk's .md file with retried page content.

    The .md file has format:
    ## Page X
    [content]

    ## Page Y
    [content]
    """
    md_file = chunk_dir / f"{chunk_dir.name}.md"
    if not md_file.exists():
        return False

    try:
        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse JSON response to extract body_text
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', new_content)
            if json_match:
                data = json.loads(json_match.group())
                body_text = data.get('body_text', new_content)
            else:
                body_text = new_content
        except:
            body_text = new_content

        # Find and replace the page section
        # Pattern: ## Page X\n[content until next ## Page or end]
        pattern = rf'(## Page {page_num}\n).*?(?=\n## Page |\Z)'

        replacement = f"## Page {page_num}\n\n{body_text}\n"

        new_content_full, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

        if count == 0:
            # Page section not found - might need to insert
            # For now, just append
            new_content_full = content + f"\n\n## Page {page_num}\n\n{body_text}\n"

        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(new_content_full)

        return True

    except Exception as e:
        print(f"    Error updating markdown: {e}")
        return False


def insert_placeholder(chunk_dir: Path, page_num: int, error_msg: str) -> bool:
    """
    Insert a placeholder for permanently failed pages.
    """
    placeholder = f"""[Page {page_num}: Conversion failed after retry]

**Error**: {error_msg}

**Original image**: images/page_{page_num:03d}.png

*This page requires manual review.*
"""
    return update_markdown_file(chunk_dir, page_num, placeholder)


def update_validation_file(chunk_dir: Path, page_num: int, success: bool, new_error: str = None):
    """
    Update the validation.yaml file to reflect retry results.
    """
    validation_file = chunk_dir / f"{chunk_dir.name}.validation.yaml"
    if not validation_file.exists():
        return

    try:
        with open(validation_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            return

        # Update failed_pages_detail
        failed_details = data.get('failed_pages_detail', [])
        new_failed_details = []

        for failure in failed_details:
            if failure.get('page') == page_num:
                if success:
                    # Remove from failed list
                    continue
                else:
                    # Update error message
                    failure['error'] = f"[RETRY FAILED] {new_error}"
                    failure['retry_attempted'] = True
                    new_failed_details.append(failure)
            else:
                new_failed_details.append(failure)

        data['failed_pages_detail'] = new_failed_details

        # Update statistics
        if success:
            data['page_statistics']['failed_pages'] = max(0, data['page_statistics'].get('failed_pages', 0) - 1)
            data['page_statistics']['successful_pages'] = data['page_statistics'].get('successful_pages', 0) + 1
            total = data['page_statistics'].get('total_pages', 1)
            data['page_statistics']['success_rate'] = data['page_statistics']['successful_pages'] / total

        # Add retry metadata
        if 'retry_info' not in data:
            data['retry_info'] = {
                'retry_date': datetime.now().isoformat(),
                'pages_retried': 0,
                'pages_recovered': 0,
                'pages_permanently_failed': 0
            }

        data['retry_info']['pages_retried'] = data['retry_info'].get('pages_retried', 0) + 1
        if success:
            data['retry_info']['pages_recovered'] = data['retry_info'].get('pages_recovered', 0) + 1
        else:
            data['retry_info']['pages_permanently_failed'] = data['retry_info'].get('pages_permanently_failed', 0) + 1

        with open(validation_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    except Exception as e:
        print(f"    Warning: Could not update validation file: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Retry failed pages from DocMind processing')
    parser.add_argument('--chunks-dir', type=str, required=True,
                        help='Directory containing chunk outputs')
    parser.add_argument('--api-keys', type=str, required=True,
                        help='Path to API keys file')
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                        help=f'Model to use (default: {DEFAULT_MODEL})')
    parser.add_argument('--output', type=str, default=None,
                        help='Output file for retry failures report (default: chunks_dir/retry_failures.yaml)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Scan and report but do not retry')

    args = parser.parse_args()

    chunks_dir = Path(args.chunks_dir)
    if not chunks_dir.exists():
        print(f"Error: Chunks directory not found: {chunks_dir}")
        sys.exit(1)

    api_keys_file = Path(args.api_keys)
    api_keys = load_api_keys(api_keys_file)
    if not api_keys and not args.dry_run:
        print(f"Error: No API keys found in {api_keys_file}")
        sys.exit(1)

    output_file = Path(args.output) if args.output else chunks_dir / "retry_failures.yaml"

    print("=" * 70)
    print("DocMind Retry Failed Pages")
    print("=" * 70)
    print(f"Chunks directory: {chunks_dir}")
    print(f"API keys loaded: {len(api_keys)}")
    print(f"Model: {args.model}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Scan for failed pages
    print("Scanning validation files for failed pages...")
    failed_pages = scan_validation_files(chunks_dir)

    total_failures = sum(len(pages) for pages in failed_pages.values())
    retryable = sum(1 for pages in failed_pages.values() for p in pages if p['should_retry'])
    skipped = total_failures - retryable

    print(f"\nFound {total_failures} failed pages across {len(failed_pages)} chunks:")
    print(f"  - Retryable (transient errors): {retryable}")
    print(f"  - Skipped (content moderation): {skipped}")
    print()

    if args.dry_run:
        print("DRY RUN - No retries will be attempted")
        print("\nFailed pages detail:")
        for chunk_name, pages in failed_pages.items():
            print(f"\n  {chunk_name}:")
            for p in pages:
                status = "RETRY" if p['should_retry'] else "SKIP"
                print(f"    Page {p['page']}: [{status}] {p['reason']}")
        return

    if retryable == 0:
        print("No retryable pages found. Exiting.")
        return

    # Retry pages
    print(f"\nRetrying {retryable} pages...")
    print("-" * 70)

    results = {
        'retry_date': datetime.now().isoformat(),
        'total_failures': total_failures,
        'attempted_retries': 0,
        'successful_retries': 0,
        'permanent_failures': [],
        'skipped_pages': []
    }

    key_index = 0

    for chunk_name, pages in failed_pages.items():
        chunk_dir = Path(pages[0]['chunk_dir'])

        for page_info in pages:
            if not page_info['should_retry']:
                results['skipped_pages'].append({
                    'chunk': chunk_name,
                    'page': page_info['page'],
                    'error': page_info['error'],
                    'reason': page_info['reason']
                })
                continue

            page_num = page_info['page']
            print(f"  [{chunk_name}] Page {page_num}...", end=" ", flush=True)

            results['attempted_retries'] += 1

            # Retry the page
            success, result, key_index = retry_single_page(
                page_info, api_keys, key_index, args.model
            )

            if success:
                # Update markdown file
                if update_markdown_file(chunk_dir, page_num, result):
                    print("SUCCESS")
                    results['successful_retries'] += 1
                    update_validation_file(chunk_dir, page_num, True)
                else:
                    print("FAILED (could not update file)")
                    results['permanent_failures'].append({
                        'chunk': chunk_name,
                        'page': page_num,
                        'error': "Could not update markdown file"
                    })
                    insert_placeholder(chunk_dir, page_num, "File update failed")
                    update_validation_file(chunk_dir, page_num, False, "File update failed")
            else:
                print(f"FAILED ({result[:50]}...)")
                results['permanent_failures'].append({
                    'chunk': chunk_name,
                    'page': page_num,
                    'error': result
                })
                insert_placeholder(chunk_dir, page_num, result)
                update_validation_file(chunk_dir, page_num, False, result)

            # Small delay between retries
            time.sleep(0.5)

    # Summary
    print()
    print("=" * 70)
    print("Retry Summary")
    print("=" * 70)
    print(f"Total failed pages: {total_failures}")
    print(f"Retry attempts: {results['attempted_retries']}")
    print(f"Successful retries: {results['successful_retries']}")
    print(f"Permanent failures: {len(results['permanent_failures'])}")
    print(f"Skipped (content moderation): {len(results['skipped_pages'])}")

    # Calculate recovery rate
    if results['attempted_retries'] > 0:
        recovery_rate = results['successful_retries'] / results['attempted_retries'] * 100
        print(f"Recovery rate: {recovery_rate:.1f}%")

    # Save results
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(results, f, default_flow_style=False, allow_unicode=True)
    print(f"\nRetry report saved to: {output_file}")

    # List permanent failures for manual review
    if results['permanent_failures']:
        print("\n" + "=" * 70)
        print("MANUAL REVIEW REQUIRED - Permanent Failures:")
        print("=" * 70)
        for failure in results['permanent_failures']:
            print(f"  {failure['chunk']} / Page {failure['page']}")
            print(f"    Error: {failure['error'][:80]}...")

    if results['skipped_pages']:
        print("\n" + "=" * 70)
        print("SKIPPED (Content Moderation) - Cannot be recovered:")
        print("=" * 70)
        for skip in results['skipped_pages'][:10]:  # Show first 10
            print(f"  {skip['chunk']} / Page {skip['page']}")
        if len(results['skipped_pages']) > 10:
            print(f"  ... and {len(results['skipped_pages']) - 10} more")


if __name__ == "__main__":
    main()
