import json
from pathlib import Path

import pytest

from promptbatch import checks, config, runner, tasks


def test_task_with_header_system_and_prompt(tmp_path):
    f = tmp_path / "t.md"
    f.write_text(
        '+++\nmodel = "claude-sonnet-5-5"\nmax_tokens = 500\neffort = "low"\nchecks = ["html"]\n+++\n'
        "Be brief.\n---prompt---\nHello {{name}}: {{content}} ({{language}})\n"
    )
    t = tasks.load(f)
    assert (t.model, t.max_tokens, t.effort, t.checks, t.system) == ("claude-sonnet-5-5", 500, "low", ["html"], "Be brief.")
    assert t.build("TEXT", "a", {"language": "en"}) == "Hello a: TEXT (en)"


def test_spanish_placeholders_of_version_0_1_still_work(tmp_path):
    f = tmp_path / "t.md"
    f.write_text("Traduce «{{nombre}}»: {{contenido}}")
    assert tasks.load(f).build("TEXT", "a") == "Traduce «a»: TEXT"


def test_task_without_content_fails(tmp_path):
    f = tmp_path / "t.md"
    f.write_text("no placeholder")
    with pytest.raises(SystemExit):
        tasks.load(f)


def test_unknown_header_key(tmp_path):
    f = tmp_path / "t.md"
    f.write_text('+++\nmodelo = "x"\n+++\n{{content}}')
    with pytest.raises(SystemExit):
        tasks.load(f)


def test_html_check_finds_changes():
    source = '<p>Hola <a href="http://a">x</a></p><img src="i.png">'
    assert checks.html(source, '<p>Hello <a href="http://a">x</a></p><img src="i.png">') == []
    assert checks.html(source, "<p>Hello</p>")  # loses the link and the image
    assert checks.non_empty("a" * 100, "")
    assert checks.CHECKS["no-vacio"] is checks.non_empty  # the 0.1 name still works


def test_prepare_skips_what_is_done(tmp_path):
    (tmp_path / "in").mkdir()
    for n in "abc":
        (tmp_path / "in" / f"{n}.txt").write_text(n)
    output = tmp_path / "out"
    (output / "_revisar").mkdir(parents=True)
    (output / "a.txt").write_text("done")
    (output / "_revisar" / "b.txt").write_text("to review, from version 0.1")
    files = tasks.input_files([str(tmp_path / "in")], [".txt"])
    assert [j.file.name for j in runner.prepare(files, output, False)] == ["c.txt"]
    assert len(runner.prepare(files, output, True)) == 3


def test_cost_and_batch_discount():
    p = config.load_prices(None)
    assert config.cost(p, "claude-opus-5-5", 1_000_000, 1_000_000) == 24.0
    assert config.cost(p, "claude-opus-5-5", 1_000_000, 1_000_000, batch=True) == 12.0
    assert config.cost(p, "unknown-model", 1, 1) is None


def test_cost_with_cache():
    p = config.load_prices(None)
    # Sonnet 5.5: 1M written to the cache (1.25 × 2) + 1M read (0.20) = 2.70
    assert round(config.cost(p, "claude-sonnet-5-5", 0, 0, cache_written=1_000_000, cache_read=1_000_000), 4) == 2.70


def test_long_input_price():
    p = config.load_prices(None)
    assert round(config.cost(p, "claude-haiku-5-5", 100_000, 1000), 6) == round((100_000 * 0.10 + 1000 * 0.50) / 1e6, 6)
    assert round(config.cost(p, "claude-haiku-5-5", 200_000, 1000), 6) == round((200_000 * 0.50 + 1000 * 2.50) / 1e6, 6)


def test_own_prices(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text('["model-x"]\ninput = 1.0\noutput = 2.0\n')
    assert config.load_prices(str(f))["model-x"] == (1.0, 2.0, 0.1)


def test_task_with_schema_and_context(tmp_path):
    (tmp_path / "guide.md").write_text("Use the informal you.")
    (tmp_path / "s.json").write_text(
        '{"type":"object","properties":{"content":{"type":"string"}},"required":["content"],"additionalProperties":false}'
    )
    f = tmp_path / "t.md"
    f.write_text(
        '+++\ncontext = ["guide.md"]\nschema = "s.json"\nchecks = ["html:content"]\n+++\nYou are a translator.\n---prompt---\n{{content}}'
    )
    t = tasks.load(f)
    assert t.output_extension == ".json"
    system = t.full_system()
    assert system.startswith("You are a translator.") and '<document name="guide.md">' in system and "informal you" in system
    p = runner.request_params(t, "<p>x</p>", "a", None)
    assert p["output_config"]["format"]["type"] == "json_schema"
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert runner.output_name(t, Path("a.html")) == "a.json"


def test_check_on_json_field():
    source = '<p><a href="u">x</a></p>'
    assert checks.run(["html:content"], source, '{"content": "<p><a href=\\"u\\">y</a></p>"}', is_json=True) == []
    assert checks.run(["html:content"], source, '{"content": "<p>y</p>"}', is_json=True)
    assert checks.run([], source, "not json", is_json=True)
    assert checks.run(["html:title"], source, '{"content": "x"}', is_json=True) == ['missing text field "title" in the answer']


def test_field_check_against_json_input_field():
    source = '{"title": "T", "content": "<p><a href=\\"u\\">x</a></p>"}'
    assert checks.run(["html:content"], source, '{"content": "<p><a href=\\"u\\">y</a></p>"}', is_json=True) == []


def test_task_with_tools(tmp_path):
    f = tmp_path / "t.md"
    f.write_text('+++\ntools = ["web_fetch"]\ntool_max_uses = 5\nfetch_max_tokens = 1000\n+++\n{{content}}')
    p = runner.request_params(tasks.load(f), "x", "a", None)
    assert p["tools"] == [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5, "max_content_tokens": 1000}]
    f.write_text('+++\ntools = ["browser"]\n+++\n{{content}}')
    with pytest.raises(SystemExit):
        tasks.load(f)


def test_final_text_after_tools():
    class B:
        def __init__(self, type, text=""):
            self.type, self.text = type, text

    class M:
        content = (B("text", "Let me look."), B("server_tool_use"), B("web_fetch_tool_result"), B("text", '{"ok": 1}'))

    assert runner.final_text(M()) == '{"ok": 1}'


def test_attached_images(tmp_path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n")
    f = tmp_path / "t.md"
    f.write_text('+++\nimages = "images"\n+++\n{{content}}')
    t = tasks.load(f)
    p = runner.request_params(t, '{"images": ["a.png"], "text": "x"}', "n", None, None, tmp_path)
    c = p["messages"][0]["content"]
    assert c[0]["type"] == "image" and c[0]["source"]["media_type"] == "image/png" and c[-1]["type"] == "text"
    with pytest.raises(ValueError):
        runner.request_params(t, '{"images": ["missing.png"]}', "n", None, None, tmp_path)


def test_report_reads_meta_of_version_0_1(tmp_path):
    (tmp_path / ".meta").mkdir()
    (tmp_path / ".meta" / "a.json").write_text(
        json.dumps({"fichero": "a", "problemas": ["x"], "coste_usd": 0.5, "tokens_entrada": 10, "tokens_salida": 5})
    )
    (tmp_path / ".meta" / "b.json").write_text(
        json.dumps({"file": "b", "problems": [], "cost_usd": 0.25, "input_tokens": 1, "output_tokens": 2})
    )
    r = runner.report(tmp_path)
    assert (r["done"], r["to_review"], r["cost_usd"], r["tokens"]) == (1, 1, 0.75, {"input": 11, "output": 7})
    assert r["review"] == [{"file": "a", "problem": "x"}]


def test_mcp_requires_max_cost_to_spend(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from promptbatch import mcp_server

    (tmp_path / "in.txt").write_text("hello")
    task = tmp_path / "t.md"
    task.write_text("{{content}}")

    class FakeClient:
        class messages:
            @staticmethod
            def count_tokens(**_):
                return type("R", (), {"input_tokens": 100})()

    monkeypatch.setattr(config, "client", lambda *a, **k: FakeClient())
    out = str(tmp_path / "out")
    assert "estimated cost" in mcp_server.launch(str(task), [str(tmp_path / "in.txt")], out)
    for mode in ("direct", "batch"):
        assert "Not launched: pass max_cost" in mcp_server.launch(str(task), [str(tmp_path / "in.txt")], out, mode=mode)
