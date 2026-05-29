import sys

import middle


def main(*args: str, stdout=sys.stdout, stderr=sys.stderr):
    if stdout is not None:
        sys.stdout = stdout
    if stderr is not None:
        sys.stderr = stderr
    args = args or sys.argv[1:]
    assert len(args) == 3, "wrong number of arguments"
    print(middle.middle(*list(map(int, args))))


if __name__ == "__main__":
    main()
