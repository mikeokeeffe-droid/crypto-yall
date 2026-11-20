"""Read-only checks for a restricted local PostgreSQL Unix socket directory."""

import argparse
import grp
import os
import stat


def verify_socket_directory(path, group_name):
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError("socket directory must be an absolute path")
    if not isinstance(group_name, str) or not group_name:
        raise ValueError("expected socket group is required")
    try:
        info = os.lstat(path)
        expected_gid = grp.getgrnam(group_name).gr_gid
    except (OSError, KeyError) as exc:
        raise ValueError("socket directory or expected group is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("socket path must be a real directory, not a symlink")
    if stat.S_IMODE(info.st_mode) != 0o770:
        raise ValueError("socket directory mode must be exactly 0770")
    if info.st_gid != expected_gid:
        raise ValueError("socket directory does not belong to the expected group")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-dir", required=True)
    parser.add_argument("--group", required=True)
    args = parser.parse_args()
    verify_socket_directory(args.socket_dir, args.group)
    print("Unix socket directory meets the review-only 0770 group policy")


if __name__ == "__main__":
    main()
