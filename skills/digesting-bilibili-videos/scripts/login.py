#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站扫码登录入口。真正的实现在共享的 lib/bili_login.py，两个 skill 共用一份。"""
import sys

import _paths  # noqa: F401  把共享 lib 挂上 sys.path
import bili_login

if __name__ == "__main__":
    sys.exit(bili_login.main())
