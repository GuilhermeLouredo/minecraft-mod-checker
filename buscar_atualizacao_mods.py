import concurrent.futures
import hashlib
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# Habilita cores ANSI nativas no terminal do Windows
if os.name == "nt":
    os.system("")

# ==========================================
# CONFIGURAÇÕES
# ==========================================
TARGET_VERSION = "26.3"
TARGET_LOADER = "fabric"
DOWNLOAD_DIR = f"../Auxiliar_Codigos/mods_{TARGET_VERSION}"
MANIFEST_FILE = os.path.join(DOWNLOAD_DIR, "manifest.json")
MAX_WORKERS = 8          # Downloads/consultas simultâneas
MAX_RETRIES = 3          # Tentativas em caso de falha de rede/429
IGNORE_SSL = False       # Mude para True apenas se sua rede bloquear certificados SSL

HEADERS = {
    "User-Agent": "MeuModChecker/4.2 (automacao-pessoal)"
}

MODS = [
    "appleskin", "atmospherics", "orthocamera", "axiom", "better-clouds", "betterf3",
    "bettergrassify", "c2me-fabric", "chat-heads", "chatanimation", "cloth-config",
    "continuity", "dynamic-fps", "entityculling", "essential", "fabric-api",
    "carpet", "fabric-language-kotlin", "fadeless", "ferrite-core",
    "forge-config-api-port", "freecam", "gamma-utils", "geckolib", "immediatelyfast",
    "inventory-particles", "iris", "krypton", "litematica", "lithium", "malilib",
    "modmenu", "mossylib", "mouse-tweaks", "mru", "music-tweaks", "no-enderman-grief",
    "optigui", "particle-rain", "puzzles-lib", "reeses-sodium-options",
    "shulkerboxtooltip", "simply-no-shading", "3dskinlayers", "sodium-extra",
    "sodium", "status-effect-bars", "voxy", "xaeros-world-map", "yacl", "zoomify"
]

FLEXIBLE_MODS = {"essential"}


class Cor:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    VERDE = "\033[92m"
    CIANO = "\033[96m"
    AMARELO = "\033[93m"
    VERMELHO = "\033[91m"
    AZUL = "\033[94m"
    CINZA = "\033[90m"


os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ctx = ssl.create_default_context()
if IGNORE_SSL:
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

manifest_lock = threading.Lock()
print_lock = threading.Lock()


def load_manifest() -> dict:
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_manifest(manifest: dict) -> None:
    tmp_manifest = MANIFEST_FILE + ".tmp"
    with open(tmp_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, sort_keys=True)
    os.replace(tmp_manifest, MANIFEST_FILE)


def fetch_json_with_retry(url: str, timeout: int = 12):
    """Retorna (dados_json, status_code)."""
    req = urllib.request.Request(url, headers=HEADERS)
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8")), 200
        except urllib.error.HTTPError as e:
            if e.code == 429 and tentativa < MAX_RETRIES:
                time.sleep(1.5 * tentativa)
                continue
            if e.code == 404:
                return None, 404
        except Exception:
            if tentativa < MAX_RETRIES:
                time.sleep(1.0 * tentativa)
                continue
    return None, 0


def suggest_slug(mod_slug: str) -> str | None:
    """Se um slug der 404, busca o projeto mais próximo no Modrinth."""
    q = urllib.parse.quote(mod_slug.replace("-", " "))
    data, code = fetch_json_with_retry(f"https://api.modrinth.com/v2/search?query={q}&limit=1")
    if code == 200 and data and data.get("hits"):
        return data["hits"][0].get("slug")
    return None


def pick_primary_file(version_obj: dict):
    files = version_obj.get("files", [])
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary:
        return None
    return {
        "filename": primary["filename"],
        "url": primary["url"],
        "sha512": primary.get("hashes", {}).get("sha512"),
        "size": primary.get("size", 0),
        "version_number": version_obj.get("version_number", "?")
    }


def get_mod_file(mod_slug: str, target_version: str, target_loader: str):
    """Retorna (mod_data, motivo_pendente)."""
    base_url = f"https://api.modrinth.com/v2/project/{mod_slug}/version"
    loaders_param = urllib.parse.quote(json.dumps([target_loader]))
    versions_param = urllib.parse.quote(json.dumps([target_version]))

    # 1) Caminho rápido: busca exata na API
    if mod_slug not in FLEXIBLE_MODS:
        url_exact = f"{base_url}?loaders={loaders_param}&game_versions={versions_param}"
        versions, status = fetch_json_with_retry(url_exact)
        if status == 404:
            sugestao = suggest_slug(mod_slug)
            hint = f" (quis dizer '{sugestao}'?)" if sugestao else ""
            return None, f"Slug não encontrado (404){hint}"
        if versions:
            return pick_primary_file(versions[0]), None

    # 2) Fallback inteligente: busca todas as versões do loader
    url_loader = f"{base_url}?loaders={loaders_param}"
    versions, status = fetch_json_with_retry(url_loader)
    if status == 404:
        sugestao = suggest_slug(mod_slug)
        hint = f" (quis dizer '{sugestao}'?)" if sugestao else ""
        return None, f"Slug não encontrado (404){hint}"
    if not versions:
        return None, f"Sem versões para {target_loader.title()}"

    version_tags = (target_version, target_version.replace(".", "-"), target_version.replace(".", "_"))

    # 2a) Compatibilidade exata ou patch/rc/pre da mesma série (ex: 26.3.1, 26.3-rc1)
    for v in versions:
        gvs = v.get("game_versions", [])
        if any(gv == target_version or gv.startswith(target_version + ".") or gv.startswith(target_version + "-") for gv in gvs):
            result = pick_primary_file(v)
            if result:
                return result, None

    # 2b) Tag da versão presente no nome do arquivo ou número da versão
    for v in versions:
        result = pick_primary_file(v)
        v_num = str(v.get("version_number", ""))
        if result and (any(tag in result["filename"] for tag in version_tags) or any(tag in v_num for tag in version_tags)):
            return result, None

    # 2c) Fallback final exclusivo para FLEXIBLE_MODS (ex: essential)
    if mod_slug in FLEXIBLE_MODS:
        releases = [v for v in versions if v.get("version_type") == "release"]
        for v in releases:
            result = pick_primary_file(v)
            if result:
                return result, None

    # 3) Se realmente não tiver, informa a última versão suportada para diagnóstico
    ultima_gv = versions[0].get("game_versions", ["?"])[-1] if versions[0].get("game_versions") else "?"
    return None, f"Sem {target_version} (última p/ {target_loader.title()}: {ultima_gv})"


def download_and_verify(url: str, dest_path: str, expected_sha512: str | None) -> int:
    tmp_path = dest_path + ".tmp"
    req = urllib.request.Request(url, headers=HEADERS)

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            hasher = hashlib.sha512()
            total_bytes = 0

            with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
                with open(tmp_path, "wb") as out_file:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        hasher.update(chunk)
                        total_bytes += len(chunk)

            if expected_sha512 and hasher.hexdigest().lower() != expected_sha512.lower():
                raise ValueError("Hash SHA-512 inválido (arquivo corrompido)")

            os.replace(tmp_path, dest_path)
            return total_bytes

        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            if tentativa == MAX_RETRIES:
                raise
            time.sleep(1.5 * tentativa)

    return 0


def format_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def print_progress(done: int, total: int, line_msg: str) -> None:
    largura = 26
    preenchido = int(largura * done / total)
    barra = f"{Cor.CIANO}{'█' * preenchido}{Cor.CINZA}{'░' * (largura - preenchido)}{Cor.RESET}"
    pct = int((done / total) * 100)
    with print_lock:
        sys.stdout.write("\r\033[K")
        print(line_msg)
        if done < total:
            sys.stdout.write(f"  Progresso: [{barra}] {pct:3d}% ({done}/{total})")
            sys.stdout.flush()


def process_mod(mod: str, installed_manifest: dict) -> dict:
    mod_data, motivo = get_mod_file(mod, TARGET_VERSION, TARGET_LOADER)

    if not mod_data:
        return {"mod": mod, "status": "pendente", "msg": motivo or "Sem versão compatível"}

    latest_filename = mod_data["filename"]
    latest_url = mod_data["url"]
    expected_hash = mod_data["sha512"]
    dest_path = os.path.join(DOWNLOAD_DIR, latest_filename)

    with manifest_lock:
        current_installed = installed_manifest.get(mod)

    if current_installed == latest_filename and os.path.exists(dest_path):
        return {"mod": mod, "status": "em_dia", "filename": latest_filename}

    is_update = bool(current_installed and current_installed != latest_filename)
    old_file_path = os.path.join(DOWNLOAD_DIR, current_installed) if is_update else None

    try:
        bytes_dl = download_and_verify(latest_url, dest_path, expected_hash)

        if is_update and old_file_path and os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
            except OSError:
                pass

        with manifest_lock:
            installed_manifest[mod] = latest_filename
            save_manifest(installed_manifest)

        return {
            "mod": mod,
            "status": "atualizado" if is_update else "baixado",
            "filename": latest_filename,
            "bytes": bytes_dl
        }
    except Exception as e:
        return {"mod": mod, "status": "falha", "msg": str(e)}


def main():
    inicio = time.perf_counter()
    installed_manifest = load_manifest()
    total = len(MODS)

    print(f"\n{Cor.BOLD}{Cor.CIANO}╔══════════════════════════════════════════════════════════════╗{Cor.RESET}")
    print(f"{Cor.BOLD}{Cor.CIANO}║  MODRINTH SYNC v4.2  │  MC {TARGET_VERSION} ({TARGET_LOADER.title()})  │  {total} mods       ║{Cor.RESET}")
    print(f"{Cor.BOLD}{Cor.CIANO}╚══════════════════════════════════════════════════════════════╝{Cor.RESET}\n")

    resultados = {
        "em_dia": [],
        "baixado": [],
        "atualizado": [],
        "pendente": [],
        "falha": []
    }
    total_bytes = 0
    concluidos = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_mod, mod, installed_manifest): mod for mod in MODS}

        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            concluidos += 1
            st = res["status"]
            mod = res["mod"]
            resultados[st].append(res)

            if st == "em_dia":
                msg = f"  {Cor.CINZA}[EM DIA]     {mod:<24} -> {res['filename']}{Cor.RESET}"
            elif st == "baixado":
                total_bytes += res["bytes"]
                msg = f"  {Cor.VERDE}[BAIXADO]    {mod:<24} -> {res['filename']} ({format_mb(res['bytes'])}){Cor.RESET}"
            elif st == "atualizado":
                total_bytes += res["bytes"]
                msg = f"  {Cor.AZUL}[ATUALIZADO] {mod:<24} -> {res['filename']} ({format_mb(res['bytes'])}){Cor.RESET}"
            elif st == "pendente":
                msg = f"  {Cor.AMARELO}[PENDENTE]   {mod:<24} -> {res['msg']}{Cor.RESET}"
            else:
                msg = f"  {Cor.VERMELHO}[ERRO]       {mod:<24} -> {res['msg']}{Cor.RESET}"

            print_progress(concluidos, total, msg)

    arquivos_esperados = {installed_manifest.get(m) for m in MODS if m in installed_manifest}
    orfaos = [
        f for f in os.listdir(DOWNLOAD_DIR)
        if f.endswith(".jar") and f not in arquivos_esperados
    ]

    duracao = time.perf_counter() - inicio
    pasta_completa = os.path.abspath(DOWNLOAD_DIR)
    caminho_formatado = pasta_completa.replace("\\", "/")

    print(f"\n{Cor.BOLD}────────────────────────────────────────────────────────────────{Cor.RESET}")
    print(f"{Cor.BOLD}  RESUMO DA SINCRONIZAÇÃO ({duracao:.1f}s │ {format_mb(total_bytes)} baixados){Cor.RESET}")
    print(f"{Cor.BOLD}────────────────────────────────────────────────────────────────{Cor.RESET}")
    print(f"  {Cor.CINZA}● Em dia:      {len(resultados['em_dia'])}{Cor.RESET}")
    print(f"  {Cor.VERDE}● Baixados:    {len(resultados['baixado'])}{Cor.RESET}")
    print(f"  {Cor.AZUL}● Atualizados: {len(resultados['atualizado'])}{Cor.RESET}")
    print(f"  {Cor.AMARELO}● Pendentes:   {len(resultados['pendente'])}{Cor.RESET}")
    print(f"  {Cor.VERMELHO}● Falhas:      {len(resultados['falha'])}{Cor.RESET}")

    if resultados["pendente"]:
        print(f"\n{Cor.AMARELO}  Pendentes / Diagnóstico:{Cor.RESET}")
        for item in sorted(resultados["pendente"], key=lambda x: x["mod"]):
            print(f"    - {item['mod']}: {item['msg']}")

    if resultados["falha"]:
        print(f"\n{Cor.VERMELHO}  Falha no download (rode novamente):{Cor.RESET}")
        for item in sorted(resultados["falha"], key=lambda x: x["mod"]):
            print(f"    - {item['mod']} ({item['msg']})")

    if orfaos:
        print(f"\n{Cor.AMARELO}  ⚠ Arquivos .jar extras na pasta (fora da lista atual):{Cor.RESET}")
        for f in sorted(orfaos):
            print(f"    - {f}")

    print(f"\n  Pasta: {Cor.CIANO}file:///{caminho_formatado}{Cor.RESET}\n")

    if os.name == "nt":
        try:
            os.startfile(pasta_completa)
        except OSError:
            pass


if __name__ == "__main__":
    main()
