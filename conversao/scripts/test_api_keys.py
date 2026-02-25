#!/usr/bin/env python3
"""
Test all DashScope API keys to verify they're working normally.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from http import HTTPStatus
import dashscope
from dashscope import MultiModalConversation

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

def test_api_key(key_num: int, api_key: str) -> dict:
    """
    Test a single API key with a simple query.
    Returns dict with status and details.
    """
    print(f"\n{'='*60}")
    print(f"Testing API Key #{key_num}: {api_key[:15]}...{api_key[-6:]}")
    print(f"{'='*60}")

    # Set the API key for this test
    dashscope.api_key = api_key

    # Simple test prompt with a small image
    messages = [
        {
            'role': 'user',
            'content': [
                {
                    'text': 'What color is the sky on a clear day? Just answer in one word.'
                }
            ]
        }
    ]

    try:
        # Make API call
        response = MultiModalConversation.call(
            model='qwen-vl-max-latest',
            messages=messages,
            max_tokens=50
        )

        # Check response
        if response.status_code == HTTPStatus.OK:
            result_text = response.output.choices[0].message.content[0]['text']
            usage = response.usage

            print(f"✅ Status: SUCCESS")
            print(f"   Response: {result_text[:100]}")
            print(f"   Input tokens: {usage.input_tokens}")
            print(f"   Output tokens: {usage.output_tokens}")

            return {
                'key_num': key_num,
                'status': 'SUCCESS',
                'api_key': api_key,
                'response': result_text,
                'input_tokens': usage.input_tokens,
                'output_tokens': usage.output_tokens,
                'error': None
            }
        else:
            print(f"❌ Status: FAILED")
            print(f"   Code: {response.code}")
            print(f"   Message: {response.message}")

            return {
                'key_num': key_num,
                'status': 'FAILED',
                'api_key': api_key,
                'error': f"{response.code}: {response.message}"
            }

    except Exception as e:
        print(f"❌ Status: ERROR")
        print(f"   Exception: {str(e)}")

        return {
            'key_num': key_num,
            'status': 'ERROR',
            'api_key': api_key,
            'error': str(e)
        }

def main():
    """Test all 8 API keys from .env file."""

    print(f"\n{'#'*60}")
    print("# DashScope API Keys Health Check")
    print(f"# Testing all keys from: {env_path}")
    print(f"{'#'*60}")

    # Collect all API keys
    api_keys = []
    for i in range(1, 9):
        key_var = f'DASHSCOPE_API_KEY_{i}'
        key_value = os.getenv(key_var)
        if key_value:
            api_keys.append((i, key_value))
        else:
            print(f"⚠️  Warning: {key_var} not found in .env")

    if not api_keys:
        print("\n❌ ERROR: No API keys found in .env file!")
        sys.exit(1)

    print(f"\nFound {len(api_keys)} API keys to test\n")

    # Test each key
    results = []
    for key_num, api_key in api_keys:
        result = test_api_key(key_num, api_key)
        results.append(result)

    # Summary report
    print(f"\n\n{'='*60}")
    print("SUMMARY REPORT")
    print(f"{'='*60}\n")

    success_count = sum(1 for r in results if r['status'] == 'SUCCESS')
    failed_count = sum(1 for r in results if r['status'] == 'FAILED')
    error_count = sum(1 for r in results if r['status'] == 'ERROR')

    print(f"Total Keys Tested: {len(results)}")
    print(f"✅ Successful: {success_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"⚠️  Errors: {error_count}")

    # Detailed results
    print(f"\n{'─'*60}")
    print("DETAILED RESULTS:")
    print(f"{'─'*60}\n")

    for r in results:
        status_icon = "✅" if r['status'] == 'SUCCESS' else "❌"
        print(f"{status_icon} Key #{r['key_num']}: {r['api_key'][:15]}...{r['api_key'][-6:]}")
        print(f"   Status: {r['status']}")
        if r['status'] == 'SUCCESS':
            print(f"   Tokens: {r['input_tokens']} in, {r['output_tokens']} out")
        else:
            print(f"   Error: {r['error']}")
        print()

    # Exit code
    if success_count == len(results):
        print("🎉 All API keys are working normally!\n")
        sys.exit(0)
    else:
        print(f"⚠️  {failed_count + error_count} key(s) have issues - please check!\n")
        sys.exit(1)

if __name__ == '__main__':
    main()
