"""
OlmOCR API Configuration Template
Please copy this file to olmocr_api_config.py and fill in your API key
"""

# API Configuration
API_CONFIG = {
    # Select provider (recommended: qwen)
    "provider": "qwen",  # Options: qwen, cirrascale, deepinfra, parasail

    # Qwen Official API (Recommended! Low cost, fast in China, official support)
    "qwen": {
        "server": "https://dashscope.aliyuncs.com/api/v1",
        "api_key": "YOUR_QWEN_API_KEY_HERE",  # 请替换为你的 API Key
        "model": "qwen-vl-plus-latest",  # Changed to qwen-vl-plus-latest for better cost
        "price": {
            "input": 0.002,  # ¥0.002/1K tokens
            "output": 0.002,  # ¥0.002/1K tokens
            "currency": "CNY"
        }
    },

    # Third-party API servers (alternative options)
    "cirrascale": {
        "server": "https://ai2endpoints.cirrascale.ai/api",
        "api_key": "YOUR_API_KEY_HERE",  # Fill in your API key
    },

    "deepinfra": {
        "server": "https://api.deepinfra.com/v1/openai",
        "api_key": "YOUR_API_KEY_HERE",  # Fill in your API key
    },

    "parasail": {
        "server": "https://www.saas.parasail.io/api",
        "api_key": "YOUR_API_KEY_HERE",  # Fill in your API key
    },
}

def get_api_config():
    """Get currently selected API configuration"""
    provider = API_CONFIG["provider"]
    config = API_CONFIG.get(provider, {})

    if not config or config["api_key"] == "YOUR_QWEN_API_KEY_HERE" or config["api_key"] == "YOUR_API_KEY_HERE":
        raise ValueError(
            f"Please configure {provider} API key first!\n"
            f"Edit file: olmocr_api_config.py\n"
            f"Change api_key to your actual key\n\n"
            f"To get Qwen API key:\n"
            f"1. Visit https://dashscope.aliyun.com/\n"
            f"2. Register/login with Aliyun account\n"
            f"3. Go to API Keys page\n"
            f"4. Create new API key\n"
            f"5. Copy and paste the key here"
        )

    return config["server"], config["api_key"]

if __name__ == "__main__":
    try:
        server, key = get_api_config()
        print(f"✅ API configuration successful")
        print(f"   Provider: {API_CONFIG['provider']}")
        print(f"   Server: {server}")
        print(f"   Key: {key[:10]}...{key[-4:]}")
    except ValueError as e:
        print(f"❌ {e}")
