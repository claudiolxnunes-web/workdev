#!/usr/bin/env python3
# tests/test_settings_api.py

import os
import sys
from pathlib import Path

import requests

# Adiciona o diretório do projeto ao path
sys.path.insert(0, str(Path(__file__).parent.parent))


def _api_key() -> str:
    configured = os.getenv("WORKDEV_API_KEY")
    if configured:
        return configured
    env_file = Path(__file__).parent.parent / "apps" / "api" / ".env"
    if env_file.exists():
        for raw in env_file.read_text().splitlines():
            key, sep, value = raw.partition("=")
            if sep and key.strip() == "WORKDEV_API_KEY":
                return value.strip().strip("\"'")
    raise RuntimeError("WORKDEV_API_KEY não configurada")


def test_settings_api():
    """Testa o endpoint de configurações da API"""
    print("Testando o endpoint de configurações...")

    base_url = os.getenv("WORKDEV_LOCAL_API_BASE", "http://127.0.0.1:8000")
    headers = {"X-API-Key": _api_key()}

    # Teste 1: Obter configurações atuais
    print("\n1. Obtendo configurações atuais...")
    try:
        response = requests.get(f"{base_url}/api/settings", headers=headers)
        if response.status_code == 200:
            settings = response.json()
            print("   ✓ Configurações obtidas com sucesso")
            print(f"   ✓ Número de seções: {len(settings.keys())}")

            expected_sections = ["app", "api", "database", "supabase", "features"]
            for section in expected_sections:
                if section in settings:
                    print(f"   ✓ Seção '{section}' presente")
                else:
                    print(f"   ✗ Seção '{section}' ausente")

            sensitive_keys_found = []

            def check_sensitive_keys(obj, path=""):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        current_path = f"{path}.{key}" if path else key
                        if any(
                            sensitive in key.lower()
                            for sensitive in ["key", "token", "secret", "password", "auth", "credential"]
                        ):
                            sensitive_keys_found.append(current_path)
                        check_sensitive_keys(value, current_path)

            check_sensitive_keys(settings)
            if sensitive_keys_found:
                print(f"   ⚠ Chaves sensíveis encontradas (isso pode ser um problema de segurança): {sensitive_keys_found}")
            else:
                print("   ✓ Nenhuma chave sensível encontrada (como esperado)")

        else:
            print(f"   ✗ Falha ao obter configurações: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"   ✗ Erro ao obter configurações: {str(e)}")
        return False

    # Teste 2: Atualizar configurações e restaurar o valor original em seguida
    # (evita deixar config/user.json sujo se este teste for rodado contra um
    # servidor real, como produção)
    print("\n2. Testando atualização de configurações...")
    original_name = settings.get("app", {}).get("name")
    original_version = settings.get("app", {}).get("version")
    try:
        update_data = {
            "app": {
                "name": "WorkDev Core - Atualizado via Teste",
                "version": "1.0.1",
            },
        }

        response = requests.put(f"{base_url}/api/settings", json=update_data, headers=headers)
        if response.status_code == 200:
            updated_settings = response.json()
            print("   ✓ Configurações atualizadas com sucesso")

            if (
                updated_settings["app"]["name"] == "WorkDev Core - Atualizado via Teste"
                and updated_settings["app"]["version"] == "1.0.1"
            ):
                print("   ✓ Alterações aplicadas corretamente")
            else:
                print("   ✗ Alterações não aplicadas corretamente")
                return False
        else:
            print(f"   ✗ Falha ao atualizar configurações: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"   ✗ Erro ao atualizar configurações: {str(e)}")
        return False
    finally:
        # Restaura o valor original, independentemente do resultado acima
        if original_name is not None:
            requests.put(
                f"{base_url}/api/settings",
                json={"app": {"name": original_name, "version": original_version}},
                headers=headers,
            )
            print("   ↺ Valor original restaurado em config/user.json")

    # Teste 3: Tentar atualizar uma chave sensível (deve falhar)
    print("\n3. Testando proteção contra atualização de chaves sensíveis...")
    try:
        bad_update_data = {"supabase": {"anonKey": "nova_chave_proibida"}}

        response = requests.put(f"{base_url}/api/settings", json=bad_update_data, headers=headers)
        if response.status_code == 400:
            print("   ✓ Bloqueio de chave sensível funcionando corretamente")
        else:
            print(f"   ✗ Bloqueio de chave sensível falhou: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"   ✗ Erro ao testar proteção de chave sensível: {str(e)}")
        return False

    print("\n✓ Todos os testes do endpoint de configurações passaram!")
    return True


if __name__ == "__main__":
    test_settings_api()
