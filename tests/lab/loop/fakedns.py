"""Fake-Resolver für das Labor: beantwortet A-Anfragen für NAME mit ADDR, alles andere NXDOMAIN."""
import socket, struct, sys
host, port, name, addr = sys.argv[1], int(sys.argv[2]), sys.argv[3].lower(), sys.argv[4]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((host, port))
while True:
    q, a = s.recvfrom(512)
    ident, flags = struct.unpack("!HH", q[:4])
    i, labels = 12, []
    while q[i]:
        labels.append(q[i+1:i+1+q[i]].decode()); i += 1 + q[i]
    qtype = struct.unpack("!H", q[i+1:i+3])[0]; end = i + 5
    qname = ".".join(labels).lower()
    hit = qname == name and qtype == 1
    rcode = 0 if qname == name else 3
    head = struct.pack("!HHHHHH", ident, 0x8180 | (flags & 0x0100) | rcode, 1, 1 if hit else 0, 0, 0)
    body = q[12:end]
    if hit:
        body += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 5, 4) + socket.inet_aton(addr)
    s.sendto(head + body, a)
