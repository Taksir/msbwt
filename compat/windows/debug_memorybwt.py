# -*- coding: utf-8 -*-
import os
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "packages", "msbwt-modern2"))


def main():
    from MUSCython import MultimergeCython
    seq = "ACGTN$ACGTN"
    try:
        res = MultimergeCython.memoryBWT(seq)
        print("memoryBWT OK:", type(res), len(res))
    except Exception:
        traceback.print_exc()


if __name__ == '__main__':
    main()
