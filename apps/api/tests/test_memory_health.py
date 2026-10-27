from pathlib import Path

import pytest

from app.services import memory_health as mh

LIMITS = {"low": 6144, "critical": 3072, "swap": 8192}


def mem(available, swap_used=0):
    return {"MemAvailable": available, "SwapTotal": 16384, "SwapFree": 16384 - swap_used}


@pytest.mark.parametrize("available, swap_used, nivel", [
    (27000, 237, mh.OK), (6144, 0, mh.OK), (6000, 0, mh.LOW), (3071, 0, mh.CRITICAL),
    (20000, 9000, mh.LOW),   # memória sobrando, mas swap alto indica pressão
    (2000, 9000, mh.CRITICAL),
])
def test_classificacao_usa_memavailable_e_swap(available, swap_used, nivel):
    assert mh.classify(mem(available, swap_used), LIMITS) == nivel


def run(tmp_path, steps):
    """steps: lista de (instante, MemAvailable). Devolve alertas e saídas."""
    sent, results = [], []
    for instant, available in steps:
        results.append(mh.check(tmp_path / "memory.json", sent.append, now=instant,
                                reader=lambda a=available: mem(a), consumers=lambda: "llama-server 19500 MB"))
    return sent, results


def test_pico_curto_nao_alerta(tmp_path):
    sent, _ = run(tmp_path, [(0, 2000), (60, 20000), (200, 20000)])
    assert sent == []


def test_alerta_so_depois_de_persistir_e_avisa_a_normalizacao(tmp_path):
    sent, results = run(tmp_path, [(0, 5000), (60, 5000), (130, 5000), (200, 5000), (260, 20000), (400, 20000)])
    assert len(sent) == 2
    assert "baixa" in sent[0] and "llama-server 19500 MB" in sent[0]
    assert "normalizada" in sent[1]
    assert [code for _, code in results] == [0] * 6  # baixa não derruba o exit code


def test_nao_repete_antes_do_intervalo_e_repete_depois(tmp_path):
    sent, _ = run(tmp_path, [(0, 5000), (130, 5000), (600, 5000), (130 + mh.REPEAT_SECONDS + 1, 5000)])
    assert len(sent) == 2


def test_critica_falha_alto_com_exit_1_mesmo_antes_do_alerta(tmp_path):
    sent, results = run(tmp_path, [(0, 1500)])
    assert sent == [] and results == [(mh.CRITICAL, 1)]
    sent, _ = run(tmp_path, [(130, 1500)])
    assert "CRÍTICA" in sent[0]


def test_falha_de_leitura_nunca_vira_ok(tmp_path):
    sent = []
    def broken():
        raise OSError("sem /proc")
    nivel, code = mh.check(tmp_path / "m.json", sent.append, reader=broken)
    assert (nivel, code) == (mh.UNKNOWN, 1) and "não foi possível medir" in sent[0]


def test_read_meminfo_converte_kb_para_mb_e_exige_memavailable(tmp_path):
    ok = tmp_path / "ok"; ok.write_text("MemAvailable:   2097152 kB\nSwapTotal: 1048576 kB\nSwapFree: 524288 kB\n")
    assert mh.read_meminfo(str(ok)) == {"MemAvailable": 2048, "SwapTotal": 1024, "SwapFree": 512}
    ruim = tmp_path / "ruim"; ruim.write_text("MemTotal: 1 kB\n")
    with pytest.raises(ValueError):
        mh.read_meminfo(str(ruim))


def test_leitura_real_do_host_funciona():
    assert mh.read_meminfo()["MemAvailable"] > 0
