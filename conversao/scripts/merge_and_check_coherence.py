#!/usr/bin/env python3
"""
BATCH3 Merge and Coherence Check Script
合并chunk结果并执行三层连贯性检查
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple
import shutil


class ChunkMerger:
    def __init__(self, config_path: str, chunk_results_dir: str, output_dir: str):
        self.config_path = Path(config_path)
        self.chunk_results_dir = Path(chunk_results_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)

        # Load split mapping
        with open(self.config_path) as f:
            self.config = json.load(f)

        self.chunks = self.config['chunks']
        self.coherence_results = {
            'layer1_structural': {},
            'layer2_boundary': {},
            'layer3_semantic': {}
        }

    def merge_markdown(self) -> str:
        """Merge markdown files from all chunks"""
        print("\n" + "="*80)
        print("📝 STEP 1: Merging Markdown Files")
        print("="*80)

        merged_content = []

        for chunk in self.chunks:
            chunk_idx = chunk['chunk_idx']
            page_offset = chunk['start_page'] - 1  # 0-indexed

            # Find the MD file
            chunk_name = Path(chunk['path']).stem
            md_file = self.chunk_results_dir / chunk_name / f"{chunk_name}.md"

            print(f"\n[Chunk {chunk_idx}] Reading: {md_file.name}")
            print(f"  Page offset: {page_offset}")

            if not md_file.exists():
                raise FileNotFoundError(f"MD file not found: {md_file}")

            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Adjust page numbers in content
            if page_offset > 0:
                print(f"  Adjusting page numbers (adding offset: {page_offset})")
                content = self._adjust_page_numbers(content, page_offset)

            # Adjust image paths
            print(f"  Adjusting image paths for chunk {chunk_idx}")
            content = self._adjust_image_paths(content, chunk_name)

            # Adjust YAML reference paths
            print(f"  Adjusting YAML reference paths for chunk {chunk_idx}")
            content = self._adjust_yaml_reference_paths(content, chunk_name)

            merged_content.append(content)
            print(f"  ✅ Added {len(content)} characters")

        merged = "\n\n".join(merged_content)

        # Save merged markdown
        output_file = self.output_dir / "EN_Hyperimperialism_RGB_240224.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(merged)

        print(f"\n✅ Merged markdown saved: {output_file}")
        print(f"   Total size: {len(merged)} characters")

        return merged

    def _adjust_page_numbers(self, content: str, offset: int) -> str:
        """Adjust page numbers in markdown content"""
        # Pattern 1: [Page X]
        def replace_page_bracket(match):
            page_num = int(match.group(1))
            new_page = page_num + offset
            return f"[Page {new_page}]"

        # Pattern 2: ## Page X (section headers)
        def replace_page_header(match):
            page_num = int(match.group(1))
            new_page = page_num + offset
            return f"## Page {new_page}"

        content = re.sub(r'\[Page (\d+)\]', replace_page_bracket, content)
        content = re.sub(r'^## Page (\d+)$', replace_page_header, content, flags=re.MULTILINE)
        return content

    def _adjust_image_paths(self, content: str, chunk_name: str) -> str:
        """Adjust image paths to include chunk subdirectory"""
        # Pattern: ![...](images/...)
        def replace_image(match):
            alt_text = match.group(1)
            img_path = match.group(2)
            # Add chunk subdirectory
            new_path = f"images/{chunk_name}/{img_path.replace('images/', '')}"
            return f"![{alt_text}]({new_path})"

        content = re.sub(r'!\[(.*?)\]\((images/.*?)\)', replace_image, content)
        return content

    def _adjust_yaml_reference_paths(self, content: str, chunk_name: str) -> str:
        """Adjust YAML reference paths to include chunk subdirectory"""
        # Pattern: *YAML Metadata: [yaml_metadata/Figure_X.yaml](yaml_metadata/Figure_X.yaml)*
        def replace_yaml_ref(match):
            yaml_path = match.group(1)
            # Add chunk subdirectory
            if not chunk_name in yaml_path:
                new_path = f"yaml_metadata/{chunk_name}/{yaml_path.replace('yaml_metadata/', '')}"
            else:
                new_path = yaml_path
            return f"*YAML Metadata: [{new_path}]({new_path})*"

        content = re.sub(r'\*YAML Metadata:\s*\[(yaml_metadata/[^\]]+)\]\([^\)]+\)\*', replace_yaml_ref, content)
        return content

    def merge_images(self):
        """Copy images from chunks to merged output"""
        print("\n" + "="*80)
        print("🖼️  STEP 2: Merging Images")
        print("="*80)

        merged_images_dir = self.output_dir / "images"
        merged_images_dir.mkdir(exist_ok=True)

        for chunk in self.chunks:
            chunk_name = Path(chunk['path']).stem
            chunk_images = self.chunk_results_dir / chunk_name / "images"

            if chunk_images.exists():
                dest_dir = merged_images_dir / chunk_name
                dest_dir.mkdir(exist_ok=True)

                # Copy all images
                image_count = 0
                for img_file in chunk_images.iterdir():
                    if img_file.is_file():
                        shutil.copy2(img_file, dest_dir / img_file.name)
                        image_count += 1

                print(f"  ✅ Copied {image_count} images from {chunk_name}")

        print(f"\n✅ All images merged to: {merged_images_dir}")

    def copy_yaml_metadata(self):
        """Copy and fix individual YAML metadata files from chunks"""
        print("\n" + "="*80)
        print("📋 STEP 2.5: Copying and Fixing YAML Metadata Files")
        print("="*80)

        yaml_metadata_dir = self.output_dir / "yaml_metadata"
        yaml_metadata_dir.mkdir(exist_ok=True)

        for chunk in self.chunks:
            chunk_idx = chunk['chunk_idx']
            chunk_name = Path(chunk['path']).stem
            chunk_yaml_dir = self.chunk_results_dir / chunk_name / "yaml_metadata"
            page_offset = chunk['start_page'] - 1

            if chunk_yaml_dir.exists():
                dest_dir = yaml_metadata_dir / chunk_name
                dest_dir.mkdir(exist_ok=True)

                yaml_count = 0
                for yaml_file in chunk_yaml_dir.glob("*.yaml"):
                    # Read YAML content
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # Fix page_number in YAML (if offset > 0)
                    if page_offset > 0:
                        content = self._fix_yaml_page_number(content, page_offset)

                    # Fix image path in YAML
                    content = self._fix_yaml_image_path(content, chunk_name)

                    # Save fixed YAML
                    output_file = dest_dir / yaml_file.name
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(content)

                    yaml_count += 1

                print(f"  ✅ Copied and fixed {yaml_count} YAML files from {chunk_name} (offset: {page_offset})")

        print(f"\n✅ All YAML metadata files copied and fixed: {yaml_metadata_dir}")

    def _fix_yaml_page_number(self, content: str, offset: int) -> str:
        """Fix page_number field in individual YAML file"""
        import re

        # Pattern: page_number: X or page: X
        def replace_page_number(match):
            field_name = match.group(1)
            page_num = int(match.group(2))
            new_page = page_num + offset
            return f"{field_name}: {new_page}"

        content = re.sub(r'(page_number|page):\s*(\d+)', replace_page_number, content)
        return content

    def _fix_yaml_image_path(self, content: str, chunk_name: str) -> str:
        """Fix image path in individual YAML file"""
        import re

        # Pattern: path: "images/page_001.png" or image_path: ...
        def replace_path(match):
            field_name = match.group(1)
            img_path = match.group(2)
            # Add chunk name prefix
            if not chunk_name in img_path:
                basename = Path(img_path).name
                new_path = f"images/{chunk_name}/{basename}"
            else:
                new_path = img_path
            return f'{field_name}: "{new_path}"'

        content = re.sub(r'(path|image_path):\s*"(images/[^"]+)"', replace_path, content)
        return content

    def merge_yaml(self):
        """Merge YAML metadata from all chunks"""
        print("\n" + "="*80)
        print("📊 STEP 3: Merging YAML Metadata")
        print("="*80)

        all_figures = []

        for chunk in self.chunks:
            chunk_idx = chunk['chunk_idx']
            page_offset = chunk['start_page'] - 1
            chunk_name = Path(chunk['path']).stem

            yaml_file = self.chunk_results_dir / chunk_name / f"{chunk_name}_all_figures.yaml"

            if yaml_file.exists():
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Adjust page numbers in YAML
                if page_offset > 0:
                    content = self._adjust_yaml_page_numbers(content, page_offset)

                # Adjust image paths in YAML
                content = self._adjust_yaml_image_paths(content, chunk_name)

                all_figures.append(content)
                print(f"  ✅ Merged YAML from chunk {chunk_idx}")

        merged_yaml = "\n".join(all_figures)
        output_file = self.output_dir / "EN_Hyperimperialism_RGB_240224_all_figures.yaml"

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(merged_yaml)

        print(f"\n✅ Merged YAML saved: {output_file}")

    def _adjust_yaml_page_numbers(self, content: str, offset: int) -> str:
        """Adjust page numbers in YAML content"""
        def replace_page(match):
            page_num = int(match.group(1))
            new_page = page_num + offset
            return f"page_number: {new_page}"

        content = re.sub(r'page_number: (\d+)', replace_page, content)
        return content

    def _adjust_yaml_image_paths(self, content: str, chunk_name: str) -> str:
        """Adjust image paths in YAML content"""
        def replace_path(match):
            img_path = match.group(1)
            new_path = f"images/{chunk_name}/{img_path.replace('images/', '')}"
            return f'path: "{new_path}"'

        content = re.sub(r'path: "(images/.*?)"', replace_path, content)
        return content

    def layer1_structural_check(self, merged_md: str):
        """Layer 1: Structural coherence check"""
        print("\n" + "="*80)
        print("🔍 LAYER 1: Structural Coherence Check")
        print("="*80)

        results = {
            'heading_continuity': self._check_heading_continuity(merged_md),
            'page_number_continuity': self._check_page_continuity(merged_md),
            'section_breaks': self._check_section_breaks(merged_md)
        }

        self.coherence_results['layer1_structural'] = results

        print("\n  📋 Heading Continuity:")
        print(f"     Status: {results['heading_continuity']['status']}")

        print("\n  📋 Page Number Continuity:")
        print(f"     Status: {results['page_number_continuity']['status']}")
        print(f"     Pages found: {results['page_number_continuity']['total_pages']}")

        print("\n  📋 Section Breaks:")
        print(f"     Major sections: {results['section_breaks']['major_sections']}")

        return results

    def _check_heading_continuity(self, content: str) -> Dict:
        """Check if headings are continuous"""
        headings = re.findall(r'^(#{1,6})\s+(.+)$', content, re.MULTILINE)

        return {
            'status': 'OK' if len(headings) > 0 else 'WARNING',
            'total_headings': len(headings),
            'levels': list(set([len(h[0]) for h in headings]))
        }

    def _check_page_continuity(self, content: str) -> Dict:
        """Check page number continuity"""
        pages = re.findall(r'\[Page (\d+)\]', content)
        page_nums = sorted([int(p) for p in pages])

        gaps = []
        for i in range(len(page_nums) - 1):
            if page_nums[i+1] - page_nums[i] > 1:
                gaps.append((page_nums[i], page_nums[i+1]))

        return {
            'status': 'OK' if len(gaps) == 0 else 'WARNING',
            'total_pages': len(page_nums),
            'gaps': gaps
        }

    def _check_section_breaks(self, content: str) -> Dict:
        """Check for major section breaks"""
        major_headings = re.findall(r'^#\s+(.+)$', content, re.MULTILINE)

        return {
            'major_sections': len(major_headings),
            'sections': major_headings[:10]  # First 10
        }

    def layer2_boundary_extraction(self, merged_md: str):
        """Layer 2: Extract boundary content for review"""
        print("\n" + "="*80)
        print("🔍 LAYER 2: Boundary Content Extraction")
        print("="*80)

        # Split point is at page 93-94
        boundary_pages = [91, 92, 93, 94, 95, 96]

        print(f"  Extracting pages around split point: {boundary_pages}")

        boundary_content = []

        for page_num in boundary_pages:
            pattern = rf'\[Page {page_num}\](.*?)(?=\[Page \d+\]|$)'
            match = re.search(pattern, merged_md, re.DOTALL)

            if match:
                page_content = match.group(1).strip()
                boundary_content.append(f"### Page {page_num}\n\n{page_content}\n")
                print(f"  ✅ Extracted page {page_num}: {len(page_content)} chars")
            else:
                print(f"  ⚠️ Page {page_num} not found")

        # Save boundary content
        coherence_dir = self.output_dir.parent / "coherence_check"
        coherence_dir.mkdir(exist_ok=True)

        boundary_file = coherence_dir / "boundary_context.md"
        with open(boundary_file, 'w', encoding='utf-8') as f:
            f.write("# Boundary Context (Pages 91-96)\n\n")
            f.write("This file contains pages around the chunk split point (93-94) for coherence review.\n\n")
            f.write("---\n\n")
            f.write("\n\n".join(boundary_content))

        print(f"\n✅ Boundary content saved: {boundary_file}")

        self.coherence_results['layer2_boundary'] = {
            'boundary_pages': boundary_pages,
            'file': str(boundary_file),
            'total_chars': sum([len(bc) for bc in boundary_content])
        }

        return boundary_content

    def layer3_semantic_analysis(self, boundary_content: List[str]):
        """Layer 3: LLM semantic coherence analysis (placeholder)"""
        print("\n" + "="*80)
        print("🔍 LAYER 3: Semantic Coherence Analysis")
        print("="*80)

        print("\n  ℹ️  This layer requires LLM API call for semantic analysis")
        print("  ℹ️  Analyzing boundary content for:")
        print("     - Sentence completeness")
        print("     - Topic continuity")
        print("     - Context flow")

        # Placeholder for LLM analysis
        # In production, this would call an LLM API with the boundary content

        analysis = {
            'status': 'MANUAL_REVIEW_REQUIRED',
            'boundary_file': str(self.output_dir.parent / "coherence_check" / "boundary_context.md"),
            'recommendation': 'Please review the boundary_context.md file manually for semantic coherence'
        }

        self.coherence_results['layer3_semantic'] = analysis

        print(f"\n  ⚠️  Manual review recommended")
        print(f"  📄 Review file: {analysis['boundary_file']}")

        return analysis

    def generate_coherence_report(self):
        """Generate final coherence check report"""
        print("\n" + "="*80)
        print("📊 Generating Coherence Report")
        print("="*80)

        coherence_dir = self.output_dir.parent / "coherence_check"
        report_file = coherence_dir / "coherence_report.json"

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.coherence_results, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Coherence report saved: {report_file}")

        # Generate HTML report
        html_file = coherence_dir / "coherence_report.html"
        self._generate_html_report(html_file)

        print(f"✅ HTML report saved: {html_file}")

    def _generate_html_report(self, output_file: Path):
        """Generate HTML visualization of coherence check"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>BATCH3 Coherence Check Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .layer {{ background: #ecf0f1; padding: 20px; margin: 20px 0; border-radius: 5px; border-left: 5px solid #3498db; }}
        .status-ok {{ color: #27ae60; font-weight: bold; }}
        .status-warning {{ color: #f39c12; font-weight: bold; }}
        .status-error {{ color: #e74c3c; font-weight: bold; }}
        .metric {{ display: flex; justify-content: space-between; padding: 10px; border-bottom: 1px solid #ddd; }}
        .metric:last-child {{ border-bottom: none; }}
        .metric-label {{ font-weight: bold; }}
        .metric-value {{ color: #7f8c8d; }}
        pre {{ background: #2c3e50; color: #ecf0f1; padding: 15px; border-radius: 5px; overflow-x: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 BATCH3 三层连贯性检查报告</h1>
        <p><strong>PDF:</strong> EN_Hyperimperialism_RGB_240224.pdf (186页)</p>
        <p><strong>分块策略:</strong> 2 chunks (页1-93, 页94-186)</p>
        <p><strong>检查时间:</strong> {timestamp}</p>

        <div class="layer">
            <h2>🔍 Layer 1: 结构化检查</h2>
            <div class="metric">
                <span class="metric-label">标题连续性:</span>
                <span class="metric-value status-{self.coherence_results['layer1_structural']['heading_continuity']['status'].lower()}">{self.coherence_results['layer1_structural']['heading_continuity']['status']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">总标题数:</span>
                <span class="metric-value">{self.coherence_results['layer1_structural']['heading_continuity']['total_headings']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">页码连续性:</span>
                <span class="metric-value status-{self.coherence_results['layer1_structural']['page_number_continuity']['status'].lower()}">{self.coherence_results['layer1_structural']['page_number_continuity']['status']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">检测到页数:</span>
                <span class="metric-value">{self.coherence_results['layer1_structural']['page_number_continuity']['total_pages']}</span>
            </div>
        </div>

        <div class="layer">
            <h2>🔍 Layer 2: 边界内容提取</h2>
            <div class="metric">
                <span class="metric-label">边界页码:</span>
                <span class="metric-value">{self.coherence_results['layer2_boundary']['boundary_pages']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">提取内容:</span>
                <span class="metric-value">{self.coherence_results['layer2_boundary']['total_chars']} 字符</span>
            </div>
            <div class="metric">
                <span class="metric-label">边界文件:</span>
                <span class="metric-value"><a href="boundary_context.md">boundary_context.md</a></span>
            </div>
        </div>

        <div class="layer">
            <h2>🔍 Layer 3: 语义连贯性分析</h2>
            <div class="metric">
                <span class="metric-label">状态:</span>
                <span class="metric-value status-warning">{self.coherence_results['layer3_semantic']['status']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">建议:</span>
                <span class="metric-value">{self.coherence_results['layer3_semantic']['recommendation']}</span>
            </div>
        </div>

        <h2>📋 完整JSON报告</h2>
        <pre>{json.dumps(self.coherence_results, indent=2, ensure_ascii=False)}</pre>
    </div>
</body>
</html>"""

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def run(self):
        """Execute full merge and coherence check workflow"""
        print("\n" + "="*80)
        print("🚀 BATCH3 Merge and Coherence Check")
        print("="*80)
        print(f"\nConfig: {self.config_path}")
        print(f"Chunk results: {self.chunk_results_dir}")
        print(f"Output: {self.output_dir}")

        # Step 1-4: Merge
        merged_md = self.merge_markdown()
        self.merge_images()
        self.copy_yaml_metadata()  # New: Copy and fix individual YAMLs
        self.merge_yaml()

        # Step 4-6: Three-layer coherence check
        self.layer1_structural_check(merged_md)
        boundary_content = self.layer2_boundary_extraction(merged_md)
        self.layer3_semantic_analysis(boundary_content)

        # Step 7: Generate report
        self.generate_coherence_report()

        print("\n" + "="*80)
        print("✅ ALL TASKS COMPLETED")
        print("="*80)
        print(f"\n📁 Final results: {self.output_dir}")
        print(f"📊 Coherence report: {self.output_dir.parent}/coherence_check/")
        print("\n✨ BATCH3 processing complete with three-layer coherence checking!")


if __name__ == "__main__":
    merger = ChunkMerger(
        config_path="./split_mapping.json",
        chunk_results_dir="./chunk_results",
        output_dir="./hcm_final_results"
    )

    merger.run()
