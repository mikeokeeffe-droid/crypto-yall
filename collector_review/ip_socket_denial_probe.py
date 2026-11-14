"""Offline, fail-closed denial check for IP socket creation in the ACTUAL unit.

This module must only run as the second ExecStart of the reviewed offline
systemd oneshot service, after host_isolation_probe succeeds. It attempts
to *create* IPv4 and IPv6 sockets; it NEVER calls connect(), bind(), send(),
or attempts DNS resolution. Even if socket creation succeeds unexpectedly,
the socket is closed immediately, the probe returns failure, and no network
request is made.

This negative test is narrow evidence of address-family restrictions.
It cannot establish the absence of other egress paths or read/trade authority.
"""
import errno
import socket


_DENIED_ERRNOS = frozenset((errno.EAFNOSUPPORT, errno.EPERM, errno.EACCES))


def check_ip_socket_creation_denied(factory=None):
    """Return (passed, labels), and never connect to any endpoint."""
    if factory is None:
        factory = socket.socket

    passed = []
    for family, label in ((socket.AF_INET, "ipv4"), (socket.AF_INET6, "ipv6")):
        try:
            sock = factory(family, socket.SOCK_STREAM)
        except OSError as error:
            if error.errno not in _DENIED_ERRNOS:
                return False, tuple(passed)
            passed.append(label)
        else:
            # Fail closed, with no connect/bind/send attempts.
            sock.close()
            return False, tuple(passed)
    return True, tuple(passed)


def main():
    success, passed = check_ip_socket_creation_denied()
    print("collector_ipv4_socket_denied=" + str("ipv4" in passed).lower())
    print("collector_ipv6_socket_denied=" + str("ipv6" in passed).lower())
    print("collector_ip_socket_probe=" + ("pass" if success else "hold"))
    print("network_egress_verified=false")
    print("testnet_read_authorized=false")
    print("trading_authorized=false")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
