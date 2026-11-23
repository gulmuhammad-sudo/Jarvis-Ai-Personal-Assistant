"""A small pretend Gmail (IMAP) on this PC, for tests: real sockets, so imaplib's own reading of answers is tested too."""
import re
import socketserver
import threading


class FakeGmail:
    ADDRESS, PASSWORD = "me.test@gmail.com", "abcdefghijklmnop"

    def __init__(self, drafts="[Gmail]/Drafts", all_mail="[Gmail]/All Mail"):
        self.mails: dict[int, tuple[bytes, bool]] = {}            # uid -> (text, unread)
        self.inbox: list[int] = []
        self.drafts: list[bytes] = []
        self.commands: list[str] = []
        self.searches: list[str] = []
        self.logins = 0
        self.break_next = False
        self.names = {"drafts": drafts, "all": all_mail}
        me = self

        class Handler(socketserver.StreamRequestHandler):
            def out(self, data):
                self.wfile.write(data if isinstance(data, bytes) else data.encode())
                self.wfile.flush()

            def literal(self, line):
                m = re.search(rb"\{(\d+)\+?\}\r?\n$", line)
                if not m:
                    return b""
                self.out("+ go ahead\r\n")
                data = self.rfile.read(int(m.group(1)))
                self.rfile.readline()
                return data

            def handle(self):
                self.out("* OK Gimap ready\r\n")
                try:
                    while line := self.rfile.readline():
                        if not self.one(line):
                            return
                except (ConnectionError, OSError):
                    pass

            def one(self, line):
                tag, _, rest = line.decode("utf-8", "replace").strip().partition(" ")
                word = rest.split(" ")[0].upper()
                me.commands.append("LOGIN" if word == "LOGIN" else rest)
                lit = self.literal(line)
                if me.break_next and word not in ("LOGIN", "CAPABILITY", "LOGOUT"):
                    me.break_next = False
                    return False
                if word == "CAPABILITY":
                    self.out(f"* CAPABILITY IMAP4rev1 X-GM-EXT-1 UIDPLUS\r\n{tag} OK done\r\n")
                elif word == "LOGIN":
                    ok = [x.strip('"') for x in rest.split(" ")[1:]] == [me.ADDRESS, me.PASSWORD]
                    me.logins += ok
                    self.out(f"{tag} OK welcome\r\n" if ok else f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials (Failure)\r\n")
                elif word in ("EXAMINE", "SELECT"):
                    self.box = "I" if "INBOX" in rest else "A"
                    self.out(f"* {len(me.mails)} EXISTS\r\n{tag} OK [READ-ONLY] done\r\n")
                elif word == "LIST":
                    self.out('* LIST (\\HasNoChildren) "/" "INBOX"\r\n')
                    if me.names["all"]:
                        self.out(f'* LIST (\\All \\HasNoChildren) "/" "{me.names["all"]}"\r\n')
                    if me.names["drafts"]:
                        self.out(f'* LIST (\\Drafts \\HasNoChildren) "/" "{me.names["drafts"]}"\r\n')
                    self.out(f"{tag} OK done\r\n")
                elif word == "UID" and " SEARCH " in f"{rest.upper()} ":
                    uids = list(me.inbox) if self.box == "I" else list(me.mails)
                    if lit:
                        q = lit.decode("utf-8")
                        me.searches.append(q)
                        if "is:unread" in q:
                            uids = [u for u in uids if me.mails[u][1]]
                        words = [w for w in q.split() if ":" not in w]
                        uids = [u for u in uids if all(w.lower() in me.mails[u][0].decode("utf-8", "replace").lower() for w in words)]
                    elif "UNSEEN" in rest:
                        uids = [u for u in uids if me.mails[u][1]]
                    self.out(f"* SEARCH {' '.join(map(str, uids))}\r\n{tag} OK done\r\n")
                elif word == "UID" and "FETCH" in rest.upper():
                    for u in rest.split(" ")[2].split(","):
                        u = int(u)
                        if u not in me.mails:
                            continue
                        raw, unread = me.mails[u]
                        head = raw.partition(b"\r\n\r\n")[0] + b"\r\n\r\n"
                        part = re.search(r"<0\.(\d+)>", rest)
                        body, what = (head, "BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)]") if "HEADER" in rest else (raw[:int(part.group(1))], "BODY[]<0>")
                        self.out(f'* 1 FETCH (UID {u} FLAGS ({"" if unread else chr(92) + "Seen"}) INTERNALDATE "23-Nov-2026 10:00:00 +0500" RFC822.SIZE {len(raw)} {what} {{{len(body)}}}\r\n')
                        self.out(body)
                        self.out(")\r\n")
                    self.out(f"{tag} OK done\r\n")
                elif word == "APPEND":
                    me.drafts.append(lit)
                    self.out(f"{tag} OK done\r\n")
                elif word == "LOGOUT":
                    self.out(f"* BYE\r\n{tag} OK done\r\n")
                    return False
                else:
                    self.out(f"{tag} OK done\r\n" if word == "NOOP" else f"{tag} BAD {word}\r\n")
                return True

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True
        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()

    def add(self, uid, raw, unread=True, inbox=True):
        raw = raw if isinstance(raw, bytes) else raw.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        self.mails[uid] = (raw, unread)
        if inbox:
            self.inbox.append(uid)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
