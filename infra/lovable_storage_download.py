import json, os, sys, getpass, re, urllib.request, urllib.parse

URL = "https://uyrcxfypdzasdminxizq.supabase.co"
env = open("/opt/backups/lovable-repos/create-with-voice/.env").read()
m = re.search(r'PUBLISHABLE_KEY="?([^"\n]+)', env)
ANON = m.group(1).strip()
print("anon key carregada do repo:", ANON[:20] + "...")

email = input("email do app: ").strip()
senha = getpass.getpass("senha do app: ")

def req(path, data=None, token=None, raw=False):
    r = urllib.request.Request(URL + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"apikey": ANON, "Content-Type": "application/json",
                 "Authorization": "Bearer " + (token or ANON)})
    with urllib.request.urlopen(r, timeout=30) as resp:
        b = resp.read()
        return b if raw else json.loads(b)

auth = req("/auth/v1/token?grant_type=password",
           {"email": email, "password": senha})
tok = auth["access_token"]
print("logado como", auth["user"]["email"])

DEST = "/opt/backups/lovable-storage"
buckets = ["documentos_bpf", "documentos-bpf", "feed-bpf",
           "normas_legislacao", "relatorios"]
total = 0

def listar(bucket, prefixo=""):
    return req("/storage/v1/object/list/" + bucket,
               {"prefix": prefixo, "limit": 1000,
                "sortBy": {"column": "name", "order": "asc"}}, tok)

def varrer(bucket, prefixo=""):
    global total
    for item in listar(bucket, prefixo):
        nome = (prefixo + "/" if prefixo else "") + item["name"]
        if item.get("id") is None:
            varrer(bucket, nome)
        else:
            destino = os.path.join(DEST, bucket, nome)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            nome_url = urllib.parse.quote(nome)
            dados = req("/storage/v1/object/authenticated/" + bucket + "/" + nome_url,
                        token=tok, raw=True)
            open(destino, "wb").write(dados)
            total += 1
            print("  baixado:", bucket + "/" + nome, "(" + str(len(dados)//1024) + " KB)")

for b in buckets:
    print("--- bucket", b)
    try:
        varrer(b)
    except Exception as e:
        print("  AVISO", type(e).__name__, str(e)[:80])

print("=== TOTAL:", total, "arquivos em", DEST)
