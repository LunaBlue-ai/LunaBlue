#!/usr/bin/env python3
"""
setup_environment.py
Cross-platform environment setup utility for LunaBlue
"""

import os
import sys
import platform
import subprocess
from pathlib import Path

class EnvironmentSetup:
    """Setup and validate LunaBlue environment"""

    def __init__(self):
        self.os_type = platform.system()
        self.python_version = sys.version_info
        self.base_path = Path(__file__).parent.parent

    def check_nodejs(self) -> bool:
        """Check if Node.js is installed"""
        try:
            result = subprocess.run(['node', '--version'], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✓ Node.js: {result.stdout.strip()}")
                return True
        except FileNotFoundError:
            print("✗ Node.js: Not found. Please install from https://nodejs.org/")
            return False

    def check_python(self) -> bool:
        """Check Python version"""
        if sys.version_info >= (3, 9):
            print(f"✓ Python: {sys.version}")
            return True
        else:
            print(f"✗ Python: Version {sys.version_info.major}.{sys.version_info.minor} found. Python 3.9+ required.")
            return False

    def check_disk_space(self) -> bool:
        """Check available disk space"""
        try:
            import shutil
            total, used, free = shutil.disk_usage(self.base_path)
            free_gb = free / (1024 ** 3)
            if free_gb >= 8:
                print(f"✓ Disk Space: {free_gb:.1f}GB available")
                return True
            else:
                print(f"✗ Disk Space: Only {free_gb:.1f}GB available. 8GB+ required.")
                return False
        except Exception as e:
            print(f"⚠ Disk Space: Could not check - {e}")
            return True

    def check_permissions(self) -> bool:
        """Check write permissions"""
        try:
            test_file = self.base_path / '.write_test'
            test_file.touch()
            test_file.unlink()
            print("✓ Permissions: Write access OK")
            return True
        except Exception as e:
            print(f"✗ Permissions: {e}")
            return False

    def run_all_checks(self) -> bool:
        """Run all environment checks"""
        print("\n" + "="*50)
        print("LunaBlue Environment Setup Check")
        print("="*50 + "\n")

        checks = [
            ("OS Detection", lambda: True),
            ("Python Version", self.check_python),
            ("Node.js", self.check_nodejs),
            ("Disk Space", self.check_disk_space),
            ("Write Permissions", self.check_permissions),
        ]

        results = []
        for name, check in checks:
            print(f"\nChecking {name}...")
            try:
                result = check()
                results.append(result)
            except Exception as e:
                print(f"✗ {name}: {e}")
                results.append(False)

        print("\n" + "="*50)
        if all(results):
            print("✓ All checks passed!")
            print("="*50 + "\n")
            return True
        else:
            print("✗ Some checks failed. Please review above.")
            print("="*50 + "\n")
            return False

if __name__ == '__main__':
    setup = EnvironmentSetup()
    success = setup.run_all_checks()
    sys.exit(0 if success else 1)
