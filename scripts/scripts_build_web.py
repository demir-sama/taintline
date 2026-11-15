"""Bundle web/ into dist/ as 4 files (Vercel connector limit): index.html (CSS inlined), app.js, data.json, vercel.json."""
import json, shutil
from pathlib import Path
R = Path(__file__).resolve().parent.parent; W = R / "web"; D = R / "dist"
shutil.rmtree(D, ignore_errors=True); D.mkdir()
html = (W / "index.html").read_text().replace('<link rel="stylesheet" href="styles.css">', "<style>\n" + (W / "styles.css").read_text() + "</style>")
(D / "index.html").write_text(html)
js = (W / "app.js").read_text()
old = js[js.index("const [bench, ans, load] = await Promise.all(["):js.index("]);", js.index("const [bench, ans, load]")) + 3]
js = js.replace(old, "const { bench, answers: ans, load } = await fetch('data.json').then((r) => r.json());")
(D / "app.js").write_text(js)
data = {"bench": json.loads((W / "data/bench.json").read_text()), "answers": json.loads((W / "data/answers.json").read_text()),
        "load": json.loads((W / "data/load.json").read_text())}
(D / "data.json").write_text(json.dumps(data, separators=(",", ":")))
shutil.copy(W / "vercel.json", D / "vercel.json")
print(sorted(p.name for p in D.iterdir()))
