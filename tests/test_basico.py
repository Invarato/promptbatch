from pathlib import Path

import pytest

from promptbatch import checks, config, runner, tasks


def test_tarea_con_cabecera_system_y_prompt(tmp_path):
    f = tmp_path / "t.md"
    f.write_text('+++\nmodel = "claude-sonnet-5-5"\nmax_tokens = 500\neffort = "low"\nchecks = ["html"]\n+++\nSé breve.\n---prompt---\nHola {{nombre}}: {{contenido}} ({{idioma}})\n')
    t = tasks.cargar(f)
    assert (t.model, t.max_tokens, t.effort, t.checks, t.system) == ("claude-sonnet-5-5", 500, "low", ["html"], "Sé breve.")
    assert t.construir("TEXTO", "a", {"idioma": "en"}) == "Hola a: TEXTO (en)"


def test_tarea_sin_contenido_falla(tmp_path):
    f = tmp_path / "t.md"
    f.write_text("sin variable")
    with pytest.raises(SystemExit):
        tasks.cargar(f)


def test_clave_desconocida_en_cabecera(tmp_path):
    f = tmp_path / "t.md"
    f.write_text('+++\nmodelo = "x"\n+++\n{{contenido}}')
    with pytest.raises(SystemExit):
        tasks.cargar(f)


def test_check_html_detecta_cambios():
    entrada = '<p>Hola <a href="http://a">x</a></p><img src="i.png">'
    assert checks.html(entrada, '<p>Hello <a href="http://a">x</a></p><img src="i.png">') == []
    assert checks.html(entrada, '<p>Hello</p>')   # pierde enlace e imagen
    assert checks.no_vacio("a" * 100, "")


def test_preparar_salta_lo_ya_hecho(tmp_path):
    (tmp_path / "in").mkdir()
    for n in "ab":
        (tmp_path / "in" / f"{n}.txt").write_text(n)
    salida = tmp_path / "out"
    salida.mkdir()
    (salida / "a.txt").write_text("hecho")
    ficheros = tasks.ficheros_de_entrada([str(tmp_path / "in")], [".txt"])
    assert [t.fichero.name for t in runner.preparar(ficheros, salida, False)] == ["b.txt"]
    assert len(runner.preparar(ficheros, salida, True)) == 2


def test_coste_y_descuento_de_lote():
    p = config.cargar_precios(None)
    assert config.coste(p, "claude-opus-5-5", 1_000_000, 1_000_000) == 24.0
    assert config.coste(p, "claude-opus-5-5", 1_000_000, 1_000_000, batch=True) == 12.0
    assert config.coste(p, "modelo-raro", 1, 1) is None
