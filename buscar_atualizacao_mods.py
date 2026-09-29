import json
import urllib.request
import urllib.error
import ssl
import os

TARGET_VERSION = "26.3"
TARGET_LOADER = "fabric"
DOWNLOAD_DIR = f"../Auxiliar_Codigos/mods_{TARGET_VERSION}"
MANIFEST_FILE = os.path.join(DOWNLOAD_DIR, "manifest.json")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

headers = {
    "User-Agent": "MeuModChecker/3.0 (automacao-pessoal)"
}

mods = [
    "appleskin", "atmospherics", "orthocamera", "axiom", "better-clouds", "betterf3",
    "bettergrassify", "c2me-fabric", "chat-heads", "chatanimation", "cloth-config",
    "continuity", "dynamic-fps", "entityculling", "essential", "fabric-api",
    "carpet", "fabric-language-kotlin", "fadeless", "ferrite-core",
    "forge-config-api-port", "freecam", "gamma-utils", "geckolib", "immediatelyfast",
    "inventory-particles", "iris", "krypton", "litematica", "lithium", "malilib",
    "modmenu", "mossylib", "mouse-tweaks", "mru", "music-tweaks", "no-enderman-grief",
    "optigui", "particlerain", "puzzles-lib", "reeses-sodium-options",
    "shulkerboxtooltip", "simply-no-shading", "3dskinlayers", "sodium-extra",
    "sodium", "status-effect-bars", "voxy", "xaeros-world-map", "yacl", "zoomify"
]

FLEXIBLE_MODS = {"essential"}

def load_manifest():
    """Carrega o histórico de mods baixados."""
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_manifest(manifest):
    """Salva o histórico atualizado de arquivos baixados."""
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)

def get_mod_file(mod_slug, target_version, target_loader):
    """Retorna o .jar mais recente com compatibilidade exata.
    Para mods em FLEXIBLE_MODS, cai para o mais recente do loader se não houver exata."""
    url = f"https://api.modrinth.com/v2/project/{mod_slug}/version"
    req = urllib.request.Request(url, headers=headers)

    def pick_file(v):
        files = v.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if primary:
            return {"filename": primary["filename"], "url": primary["url"]}
        return None

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            if response.status != 200:
                return None
            versions = json.loads(response.read().decode())
    except Exception:
        return None

    for v in versions:
        if target_version in v.get("game_versions", []) and target_loader in v.get("loaders", []):
            result = pick_file(v)
            if result:
                return result

    if mod_slug in FLEXIBLE_MODS:
        loader_versions = [
            v for v in versions
            if target_loader in v.get("loaders", []) and v.get("version_type") == "release"
        ]

        version_tags = (target_version.replace(".", "-"), target_version)
        for v in loader_versions:
            result = pick_file(v)
            if result and any(tag in result["filename"] for tag in version_tags):
                return result

        for v in loader_versions:
            result = pick_file(v)
            if result:
                return result

    return None

def download_file(url, destination_path):
    """Faz o stream de download do arquivo .jar."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        with open(destination_path, "wb") as out_file:
            out_file.write(resp.read())

installed_manifest = load_manifest()

print(f"Sincronizando mods APENAS para a versão final {TARGET_VERSION} ({TARGET_LOADER.title()})...\n")

for mod in mods:
    mod_data = get_mod_file(mod, TARGET_VERSION, TARGET_LOADER)

    if not mod_data:
        print(f"[PENDENTE]    {mod:<22} -> Sem versão final estável")
        continue

    latest_filename = mod_data["filename"]
    latest_url = mod_data["url"]
    current_installed = installed_manifest.get(mod)

    dest_path = os.path.join(DOWNLOAD_DIR, latest_filename)

    if current_installed == latest_filename and os.path.exists(dest_path):
        print(f"[EM DIA]      {mod:<22} -> {latest_filename}")
        continue

    old_file_path = os.path.join(DOWNLOAD_DIR, current_installed) if current_installed else None

    if current_installed and current_installed != latest_filename and os.path.exists(old_file_path):
        print(f"[ATUALIZANDO] {mod:<22} -> Removendo {current_installed}...", end=" ", flush=True)
        try:
            os.remove(old_file_path)
        except Exception as e:
            print(f"\n[ERRO CLEAN]  Não foi possível remover {current_installed}: {e}")
        print(f"Baixando {latest_filename}...", end=" ", flush=True)

    else:
        print(f"[BAIXANDO]    {mod:<22} -> {latest_filename}...", end=" ", flush=True)

    try:
        download_file(latest_url, dest_path)
        installed_manifest[mod] = latest_filename
        save_manifest(installed_manifest)
        print("Concluído!")
    except Exception as e:
        print(f"Falha ao baixar ({e})")

pasta_completa = os.path.abspath(DOWNLOAD_DIR)
caminho_formatado = pasta_completa.replace("\\", "/")

print("\nSincronização finalizada!")
print(f"Clique para abrir (Ctrl + Clique): file:///{caminho_formatado}")
os.startfile(pasta_completa)
