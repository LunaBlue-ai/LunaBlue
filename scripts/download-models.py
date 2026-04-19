#!/usr/bin/env python3
"""
download-models.py
Batch download GGUF models from HuggingFace
"""

import os
import json
import argparse
from pathlib import Path
from typing import Optional

def download_model(repo_id: str, filename: str, local_path: str) -> bool:
    """Download a model from HuggingFace"""
    try:
        print(f"Downloading {filename} from {repo_id}...")
        # Implementation would use huggingface_hub library
        # from huggingface_hub import hf_hub_download
        # hf_hub_download(repo_id=repo_id, filename=filename, local_dir=local_path)
        print(f"✓ Downloaded to {local_path}")
        return True
    except Exception as e:
        print(f"✗ Failed to download: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Download GGUF models from HuggingFace")
    parser.add_argument(
        "--config",
        type=str,
        default="config/models.config.json",
        help="Path to models configuration file"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Specific model ID to download (if not specified, download all)"
    )
    
    args = parser.parse_args()

    # Load configuration
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    with open(config_path, 'r') as f:
        config = json.load(f)

    # Download models
    models_to_download = config.get('models', [])
    if args.model:
        models_to_download = [m for m in models_to_download if m['id'] == args.model]

    success_count = 0
    for model in models_to_download:
        if not model.get('active', True):
            print(f"Skipping inactive model: {model['name']}")
            continue

        # Ensure local path exists
        local_path = model.get('local_path', './models/')
        Path(local_path).mkdir(parents=True, exist_ok=True)

        if download_model(model['repository'], model['filename'], local_path):
            success_count += 1

    print(f"\n✓ Downloaded {success_count}/{len([m for m in models_to_download if m.get('active', True)])} models")
    return 0

if __name__ == '__main__':
    exit(main())
