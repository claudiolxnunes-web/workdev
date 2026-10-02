"""Checagens mecânicas da Bancada Local: código, sem LLM, só leitura.

A base de comparação é um commit: os arquivos saem com `git archive` para
tmp/bancada/_base/<commit>/ e o patch é testado numa cópia descartável em
tmp/bancada/_trabalho/. O repositório de trabalho nunca é tocado.

Cada achado tem categoria e severidade (erro, aviso, info). As categorias são
as mesmas que o observer LLM usa, para dar para comparar os dois.
"""
from __future__ import annotations

import ast
import io
import os
import py_compile
import re
import shutil
import subprocess
import tarfile
import uuid
from functools import lru_cache
from pathlib import Path

# A CLI roda do checkout (/opt/workdev); a API roda da release, sem .git: ela
# aponta WORKDEV_BANCADA_REPO para o checkout e WORKDEV_BANCADA_DIR para a pasta.
REPO = Path(os.environ.get("WORKDEV_BANCADA_REPO") or Path(__file__).resolve().parent.parent)
BANCADA = Path(os.environ.get("WORKDEV_BANCADA_DIR") or REPO / "tmp" / "bancada")
BASES = BANCADA / "_base"
TRABALHO = BANCADA / "_trabalho"
COMMIT_VALIDO = re.compile(r"^[0-9a-f]{7,40}$")
# Raiz dos pacotes Python da API dentro da base (app.services.x -> apps/api/app/services/x.py).
RAIZ_PY = Path("apps/api")

CATEGORIAS = {
    "diff_nao_aplica": "o diff não aplica no código real (cabeçalho, contexto ou formato)",
    "funcao_inventada": "o cabeçalho @@ cita uma função que não existe no arquivo",
    "import_inexistente": "importa módulo ou nome que não existe",
    "simbolo_inexistente": "usa nome, atributo ou constante que não existe",
    "uso_errado": "usa um nome que existe, mas no objeto errado",
    "nao_compila": "o arquivo resultante não compila",
    "fora_do_escopo": "mexe em arquivo fora do escopo da tarefa",
    "ignora_enunciado": "não faz o que o enunciado pede",
}


def achado(categoria: str, severidade: str, mensagem: str) -> dict:
    return {"categoria": categoria, "severidade": severidade, "mensagem": mensagem}


# ---------------------------------------------------------------- base

def base(commit: str, extras: list[str] | tuple[str, ...] = ()) -> Path:
    """Snapshot somente leitura de apps/api/app e scripts no commit informado.

    `extras` são caminhos fora desse núcleo (ex.: o escopo de uma tarefa de
    frontend); entram sob demanda, um a um, sem extrair o repositório inteiro.
    Caminho inexistente no commit (arquivo novo do diff) é simplesmente ignorado.
    """
    if not COMMIT_VALIDO.match(commit):
        raise ValueError(f"commit inválido: {commit!r}")
    destino = BASES / commit
    if not (destino / ".ok").exists():
        destino.mkdir(parents=True, exist_ok=True)
        _extrair(commit, destino, ["apps/api/app", "scripts"], obrigatorio=True)
        (destino / ".ok").write_text(commit)
    for caminho in extras:
        relativo = Path(caminho)
        if relativo.is_absolute() or ".." in relativo.parts or (destino / relativo).exists():
            continue
        _extrair(commit, destino, [relativo.as_posix()], obrigatorio=False)
    return destino


def _extrair(commit: str, destino: Path, caminhos: list[str], obrigatorio: bool) -> None:
    saida = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(REPO), "archive", commit, "--", *caminhos],
        capture_output=True, check=obrigatorio, timeout=60)
    if saida.returncode != 0:
        return
    with tarfile.open(fileobj=io.BytesIO(saida.stdout)) as tar:
        tar.extractall(destino, filter="data")


def ler_base(raiz: Path, caminho: str, inicio: int = 1, fim: int = 10**9) -> list[str]:
    alvo = (raiz / caminho).resolve()
    if raiz.resolve() not in alvo.parents:
        raise ValueError(f"fora da base: {caminho}")
    linhas = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
    return linhas[max(1, inicio) - 1:fim]


def modulo_para_arquivo(raiz: Path, modulo: str) -> Path | None:
    partes = modulo.split(".")
    for candidato in (raiz / RAIZ_PY / Path(*partes)).with_suffix(".py"), raiz / RAIZ_PY / Path(*partes) / "__init__.py":
        if candidato.is_file():
            return candidato
    return None


@lru_cache(maxsize=256)
def _nomes_definidos(arquivo: str) -> frozenset[str]:
    """Nomes do módulo: defs, classes, atribuições e imports em qualquer nível."""
    try:
        arvore = ast.parse(Path(arquivo).read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return frozenset()
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nomes.add(no.name)
        elif isinstance(no, ast.Assign):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    nomes.add(alvo.id)
        elif isinstance(no, (ast.AnnAssign, ast.AugAssign)) and isinstance(no.target, ast.Name):
            nomes.add(no.target.id)
        elif isinstance(no, (ast.Import, ast.ImportFrom)):
            for alias in no.names:
                nomes.add((alias.asname or alias.name).split(".")[0])
    return frozenset(nomes)


def nomes_definidos(arquivo: Path) -> frozenset[str]:
    return _nomes_definidos(str(arquivo))


def funcoes_do_arquivo(arquivo: Path) -> frozenset[str]:
    try:
        arvore = ast.parse(arquivo.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return frozenset()
    return frozenset(no.name for no in ast.walk(arvore)
                     if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))


def vinculos_de_import(arquivo: Path) -> dict[str, tuple[str, str | None]]:
    """Nome local -> (módulo, atributo|None). Atributo None = o nome é o módulo."""
    vinculos: dict[str, tuple[str, str | None]] = {}
    try:
        arvore = ast.parse(arquivo.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return vinculos
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module:
            for alias in no.names:
                vinculos[alias.asname or alias.name] = (no.module, alias.name)
        elif isinstance(no, ast.Import):
            for alias in no.names:
                vinculos[(alias.asname or alias.name).split(".")[0]] = (alias.name, None)
    return vinculos


# ---------------------------------------------------------------- proposta

FENCE = re.compile(r"```([\w+-]*)\n(.*?)```", re.S)


def extrair_diff(texto: str) -> str | None:
    for lang, corpo in FENCE.findall(texto):
        if lang == "diff" or re.search(r"^(@@|--- a/|\+\+\+ b/)", corpo, re.M):
            return corpo if corpo.endswith("\n") else corpo + "\n"
    if re.search(r"^@@ ", texto, re.M):
        return texto
    return None


def linhas_de_codigo(texto: str) -> list[str]:
    """Código proposto: linhas '+' do diff, blocos de código e trechos `inline`."""
    diff = extrair_diff(texto)
    if diff is not None:
        return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    linhas: list[str] = []
    for _lang, corpo in FENCE.findall(texto):
        linhas.extend(corpo.splitlines())
    if not linhas:
        linhas = re.findall(r"`([^`\n]+)`", texto)
    if not linhas:
        linhas = [l for l in texto.splitlines() if re.search(r"\bimport\b|=|\(", l)]
    return linhas


# ---------------------------------------------------------------- checagens

def _checar_diff(raiz: Path, diff: str, escopo: list[str]) -> tuple[list[dict], Path | None]:
    achados: list[dict] = []
    arquivos = re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)
    if not arquivos:
        achados.append(achado("diff_nao_aplica", "erro", "diff sem cabeçalho ---/+++: não dá para aplicar"))
        return achados, None
    for arquivo in arquivos:
        if escopo and arquivo not in escopo:
            achados.append(achado("fora_do_escopo", "erro", f"diff mexe em {arquivo}, fora do escopo {escopo}"))
    atual = None
    for linha in diff.splitlines():
        cabecalho = re.match(r"^\+\+\+ b/(\S+)", linha)
        if cabecalho:
            atual = cabecalho.group(1)
            continue
        hunk = re.match(r"^@@[^@]*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", linha)
        if hunk and atual and (raiz / atual).is_file() and atual.endswith(".py"):
            mensagem = f"cabeçalho @@ cita {hunk.group(1)}(), que não existe em {atual}"
            if hunk.group(1) not in funcoes_do_arquivo(raiz / atual) and not any(
                    a["mensagem"] == mensagem for a in achados):
                achados.append(achado("funcao_inventada", "erro", mensagem))
    trabalho = TRABALHO / uuid.uuid4().hex
    for arquivo in set(arquivos):
        origem = raiz / arquivo
        if origem.is_file():
            (trabalho / arquivo).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, trabalho / arquivo)
    trabalho.mkdir(parents=True, exist_ok=True)
    patch = trabalho / "proposta.patch"
    patch.write_text(diff, encoding="utf-8")
    # A cópia fica dentro do repo (tmp/): sem o teto, o git subiria até o .git
    # do WorkDev e aplicaria os caminhos a partir da raiz dele.
    isolado = {**os.environ, "GIT_CEILING_DIRECTORIES": str(TRABALHO)}
    checagem = subprocess.run(["git", "apply", "--check", "--recount", str(patch)],
                              cwd=trabalho, capture_output=True, text=True, timeout=30, env=isolado)
    if checagem.returncode != 0:
        motivo = (checagem.stderr or checagem.stdout).strip().splitlines()
        achados.append(achado("diff_nao_aplica", "erro",
                              "git apply --check falhou: " + ("; ".join(motivo[:2]) or "sem detalhe")))
        return achados, None
    subprocess.run(["git", "apply", "--recount", str(patch)], cwd=trabalho,
                   capture_output=True, text=True, timeout=30, check=True, env=isolado)
    achados.append(achado("diff_nao_aplica", "info", "git apply --check passou na cópia da base"))
    for arquivo in set(arquivos):
        if arquivo.endswith(".py") and (trabalho / arquivo).is_file():
            try:
                py_compile.compile(str(trabalho / arquivo), doraise=True,
                                   cfile=str(trabalho / (arquivo + ".pyc")))
                achados.append(achado("nao_compila", "info", f"{arquivo} compila depois do patch"))
            except py_compile.PyCompileError as erro:
                achados.append(achado("nao_compila", "erro", f"{arquivo} não compila: {str(erro.msg).strip()[:200]}"))
    return achados, trabalho


def _checar_simbolos(raiz: Path, codigo: list[str], escopo: list[str], modulos_trecho: list[str]) -> list[dict]:
    achados: list[dict] = []
    alvo = raiz / escopo[0] if escopo else None
    vinculos = vinculos_de_import(alvo) if alvo and alvo.is_file() and alvo.suffix == ".py" else {}
    definidos_alvo = nomes_definidos(alvo) if alvo and alvo.is_file() and alvo.suffix == ".py" else frozenset()
    # Funções públicas dos módulos dos trechos: servem para achar "nome certo no objeto errado".
    funcoes_conhecidas: dict[str, str] = {}
    for modulo in modulos_trecho:
        arquivo = modulo_para_arquivo(raiz, modulo)
        if arquivo:
            for nome in funcoes_do_arquivo(arquivo):
                funcoes_conhecidas.setdefault(nome, modulo)
    texto = "\n".join(codigo)
    definidos_proposta = set(re.findall(r"\b(?:def|class)\s+(\w+)", texto)) | set(re.findall(r"^\s*(\w+)\s*=", texto, re.M))

    for modulo, nomes, alias in re.findall(r"from\s+([\w.]+)\s+import\s+([\w, ]+?)(?:\s+as\s+(\w+))?\s*$", texto, re.M):
        arquivo = modulo_para_arquivo(raiz, modulo)
        nomes = [n.strip() for n in nomes.split(",") if n.strip()]
        if arquivo is None:
            # "from app.services import local_model": o nome pode ser um submódulo.
            achados.append(achado("import_inexistente", "erro", f"módulo {modulo} não existe na base"))
            continue
        for nome in nomes:
            submodulo = modulo_para_arquivo(raiz, f"{modulo}.{nome}")
            if nome not in nomes_definidos(arquivo) and submodulo is None:
                achados.append(achado("import_inexistente", "erro", f"{modulo} não tem {nome}"))
            local = alias if (alias and len(nomes) == 1) else nome
            vinculos[local] = (f"{modulo}.{nome}", None) if submodulo else (modulo, nome)
    for modulo, alias in re.findall(r"^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$", texto, re.M):
        if modulo.startswith("app.") and modulo_para_arquivo(raiz, modulo) is None:
            achados.append(achado("import_inexistente", "erro", f"módulo {modulo} não existe na base"))
        vinculos[alias or modulo.split(".")[0]] = (modulo, None)

    for objeto, atributo in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(", texto):
        if objeto in ("self", "cls", "db", "os", "json", "re", "Path", "datetime", "str", "dict", "list"):
            continue
        vinculo = vinculos.get(objeto)
        if vinculo and vinculo[1] is not None:
            achados.append(achado("uso_errado", "erro",
                                  f"{objeto} é o nome {vinculo[1]} importado de {vinculo[0]}, não um módulo: "
                                  f"{objeto}.{atributo}() falha"))
            continue
        if vinculo and vinculo[1] is None:
            arquivo = modulo_para_arquivo(raiz, vinculo[0])
            if arquivo and atributo not in nomes_definidos(arquivo):
                achados.append(achado("simbolo_inexistente", "erro", f"{vinculo[0]} não tem {atributo}"))
            continue
        dono = funcoes_conhecidas.get(atributo)
        if dono and objeto != dono.rsplit(".", 1)[-1]:
            achados.append(achado("uso_errado", "erro",
                                  f"{atributo}() é de {dono}, não de {objeto}: {objeto}.{atributo}() não existe"))

    for constante in sorted(set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", texto))):
        if constante in definidos_alvo or constante in definidos_proposta or constante in vinculos:
            continue
        if constante in {"TODO", "NOTE", "FIXME", "HTTP", "JSON", "SQL", "API", "URL", "UUID", "UTF"}:
            continue
        achados.append(achado("simbolo_inexistente", "erro",
                              f"constante {constante} não existe em {escopo[0] if escopo else 'arquivo alvo'} nem é importada"))
    return achados


def verificar(texto: str, tarefa: dict) -> dict:
    """Roda as checagens de uma proposta contra a tarefa (trechos, base, escopo, exige)."""
    escopo = list(tarefa.get("escopo") or [])
    raiz = base(tarefa["base"], [c for c, *_ in tarefa.get("trechos") or []] + escopo)
    modulos = [str(Path(c).with_suffix("")).replace("apps/api/", "").replace("/", ".")
               for c, *_ in tarefa.get("trechos") or [] if c.endswith(".py")]
    achados: list[dict] = []
    diff = extrair_diff(texto)
    if diff is not None:
        resultado, _ = _checar_diff(raiz, diff, escopo)
        achados.extend(resultado)
    elif tarefa.get("espera_diff"):
        achados.append(achado("diff_nao_aplica", "erro", "o enunciado pede diff e a proposta não traz um"))
    codigo = linhas_de_codigo(texto)
    achados.extend(_checar_simbolos(raiz, codigo, escopo, modulos))
    juntos = "\n".join(codigo)
    # Apelido de import conta como o nome original ("current as get_key" -> get_key()).
    for original, apelido in re.findall(r"import\s+(\w+)\s+as\s+(\w+)", juntos):
        juntos += "\n" + re.sub(rf"\b{apelido}\(", f"{original}(", juntos)
    # "exige" são expressões regulares: o essencial do enunciado, não um texto exato.
    for exigido, explicacao in (tarefa.get("exige") or {}).items():
        if not re.search(exigido, juntos):
            achados.append(achado("ignora_enunciado", "erro", f"a proposta não faz o pedido: {explicacao}"))
    erros = [a for a in achados if a["severidade"] == "erro"]
    return {"achados": achados, "erros": len(erros),
            "categorias_erro": sorted({a["categoria"] for a in erros}),
            "aprovada": not erros}
