#!/usr/bin/env python3
"""Test helper: static file server standing in for TSM's public-data host.

`python -m http.server` only queues 5 pending connections, which drops
concurrent requests on macOS; this one queues more.
"""

import functools
import http.server
import sys


class Server(http.server.ThreadingHTTPServer):
    request_queue_size = 64


def main():
    port, directory = int(sys.argv[1]), sys.argv[2]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with Server(("127.0.0.1", port), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
