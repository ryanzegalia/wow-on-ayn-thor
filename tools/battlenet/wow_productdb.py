"""Register an existing WoW install with Battle.net inside a Wine prefix (AYN Thor / GameNative).

Why: the Thor's WoW folder was synced from the PC without the Battle.net Agent ever seeing it. The
Agent's own "Locate the game" needs `<install>/.product.db`, and even then it keeps the PC's
`Windows x86_64` install tags, so on an ARM64 host it wants to "update" (convert to the arm64 file
set) before it shows Play. This tool writes the two records the Agent would have written itself:

  * the Agent database  ProgramData/Battle.net/Agent/product.db on the prefix's drive C:
                                                             (merge the WoW entries in)
  * the install record  <install root>/.product.db                   (same entries, path rewritten)

For every `wow*` entry it rewrites the install path (UserSettings field 1) and, with --arm64, the
installed tags string (cached state field 17) from "Windows x86_64" to "Windows arm64". Everything
else is copied byte for byte. Both inputs must round-trip through the parser unchanged or it stops.

Usage (stop Battle.net/Agent first -- the Agent rewrites product.db while it runs):
  python wow_productdb.py --folder-db "<PC WoW folder>/.product.db" \
      --agent-db agent-product.db.orig --install-path B:/ --arm64 \
      --out-agent agent-product.db.new --out-folder folder-product.db.new

Field map (reverse-engineered 2026-09-24, Agent 2.41.0.9775): top-level field 1 = ProductInstall;
ProductInstall.1 = uid, .3 = UserSettings (.1 install path, .13 subfolder e.g. "_retail_"),
.4.1 = cached base state (.1 installed, .2 playable, .3 update_complete, .7 version string,
.17 installed tags).
"""
import argparse
import sys


def _rv(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def _wv(n):
    o = bytearray()
    while True:
        c = n & 0x7F
        n >>= 7
        if n:
            o.append(c | 0x80)
        else:
            o.append(c)
            return bytes(o)


def parse(b):
    i, out = 0, []
    while i < len(b):
        key, i = _rv(b, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = _rv(b, i)
        elif w == 2:
            n, i = _rv(b, i)
            v = b[i:i + n]
            i += n
        elif w == 1:
            v = b[i:i + 8]
            i += 8
        elif w == 5:
            v = b[i:i + 4]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {w} at offset {i}")
        out.append((f, w, v))
    return out


def enc(fields):
    o = bytearray()
    for f, w, v in fields:
        o += _wv(f << 3 | w)
        if w == 0:
            o += _wv(v)
        elif w == 2:
            o += _wv(len(v)) + v
        else:
            o += v
    return bytes(o)


def uid_of(install):
    return next(v for f, w, v in parse(install) if f == 1).decode()


def rewrite_install(install, path, arm64):
    out = []
    for f, w, v in parse(install):
        if f == 3 and w == 2:  # UserSettings: .1 = install path
            v = enc([(sf, sw, path if (sf == 1 and sw == 2) else sv) for sf, sw, sv in parse(v)])
        elif f == 4 and w == 2 and arm64:  # cached state: .1 base state, .17 installed tags
            st = []
            for sf, sw, sv in parse(v):
                if sf == 1 and sw == 2:
                    sv = enc([(bf, bw, bv.replace(b"Windows x86_64", b"Windows arm64") if (bf == 17 and bw == 2) else bv)
                              for bf, bw, bv in parse(sv)])
                st.append((sf, sw, sv))
            v = enc(st)
        out.append((f, w, v))
    return enc(out)


def load(path):
    data = open(path, "rb").read()
    top = parse(data)
    if enc(top) != data:
        sys.exit(f"{path}: does not round-trip through the parser -- refusing to edit it")
    return top


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--folder-db", required=True, help="source install record (e.g. the PC's <WoW>/.product.db)")
    ap.add_argument("--agent-db", required=True, help="the prefix's current Agent product.db")
    ap.add_argument("--install-path", required=True, help='Wine path of the install root, e.g. "B:/"')
    ap.add_argument("--arm64", action="store_true", help="retag installed tags x86_64 -> arm64")
    ap.add_argument("--out-agent", required=True)
    ap.add_argument("--out-folder", required=True)
    a = ap.parse_args()

    path = a.install_path.encode()
    folder = load(a.folder_db)
    agent = load(a.agent_db)
    wow = {}
    for f, w, v in folder:
        if f == 1 and w == 2 and uid_of(v).startswith("wow"):
            wow[uid_of(v)] = rewrite_install(v, path, a.arm64)
    have = {uid_of(v) for f, w, v in agent if f == 1 and w == 2}
    added = [(1, 2, v) for u, v in wow.items() if u not in have]
    new_agent = enc(added + [(f, w, wow.get(uid_of(v), v)) if (f == 1 and w == 2) else (f, w, v) for f, w, v in agent])
    new_folder = enc([(f, w, wow.get(uid_of(v), v)) if (f == 1 and w == 2) else (f, w, v) for f, w, v in folder])
    open(a.out_agent, "wb").write(new_agent)
    open(a.out_folder, "wb").write(new_folder)
    print(f"agent db: had {sorted(have)}, added {[u for u in wow if u not in have]} -> {len(new_agent)} bytes")
    print(f"folder db: {sorted(wow)} at {a.install_path}{' (arm64 tags)' if a.arm64 else ''} -> {len(new_folder)} bytes")


if __name__ == "__main__":
    main()
