"""What: tests for the publish side: banners, READMEs, website files, install page, workflows.
Why: the release promises (circle-free banner, EN/ZH images kept apart, a site with /install, an image on ghcr) must not rot.
How: python3 -m unittest discover -s tests
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE = "https://maxont.github.io/traces.md"


class BannerTests(unittest.TestCase):
    def test_banners_exist_and_have_no_circles_rings_or_dots(self):
        for name in ("banner.svg", "banner.zh.svg"):
            svg = (DOCS / name).read_text(encoding="utf-8")
            self.assertTrue(svg.startswith("<svg"), name)
            for forbidden in ("<circle", "<ellipse"):
                self.assertNotIn(forbidden, svg, "%s must stay circle-free" % name)
            self.assertIsNone(re.search(r"\sr=\"", svg), name + " has a radius attribute")
            self.assertNotIn("stroke-linecap=\"round\"", svg, name)

    def test_zh_banner_is_chinese_and_en_banner_is_not(self):
        self.assertRegex((DOCS / "banner.zh.svg").read_text(encoding="utf-8"), r"[\u4e00-\u9fff]")
        self.assertNotRegex((DOCS / "banner.svg").read_text(encoding="utf-8"), r"[\u4e00-\u9fff]")


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.en = (ROOT / "README.md").read_text(encoding="utf-8")
        self.zh = (ROOT / "README.zh.md").read_text(encoding="utf-8")

    def test_english_readme_uses_only_english_images(self):
        images = re.findall(r'src="([^"]+)"', self.en)
        self.assertGreaterEqual(len(images), 1)
        self.assertLessEqual(len(images), 2)
        for src in images:
            self.assertNotIn(".zh.", src)
            self.assertTrue((ROOT / src).exists(), src)

    def test_chinese_readme_uses_zh_images(self):
        images = re.findall(r'src="([^"]+)"', self.zh)
        self.assertEqual(sorted(images), ["docs/assets/how-it-works.zh.gif", "docs/banner.zh.svg"])
        for src in images:
            self.assertTrue((ROOT / src).exists(), src)

    def test_readme_order_banner_note_star_install_format(self):
        order = [self.en.index(s) for s in
                 ("docs/banner.svg", "**Note.**", "star the repo", "## Install",
                  "Read https://maxont.github.io/traces.md/install and install traces for me.",
                  "curl -fsSL https://maxont.github.io/traces.md/install.sh | bash",
                  "## The format at a glance")]
        self.assertEqual(order, sorted(order))

    def test_zh_readme_has_the_same_install_lines(self):
        self.assertIn("Read https://maxont.github.io/traces.md/install and install traces for me.", self.zh)
        self.assertIn("curl -fsSL https://maxont.github.io/traces.md/install.sh | bash", self.zh)
        self.assertIn("README.md", self.zh)
        self.assertIn("README.zh.md", self.en)


class SiteTests(unittest.TestCase):
    def test_pages_and_assets_exist(self):
        for rel in ("index.html", "install/index.html", "install.sh", "banner.svg", "banner.zh.svg",
                    "assets/how-it-works.gif", "assets/how-it-works.zh.gif",
                    "assets/how-it-works.html", "assets/how-it-works.zh.html"):
            self.assertTrue((DOCS / rel).is_file(), rel)

    def test_local_links_in_home_page_resolve(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        for target in re.findall(r'(?:href|src)="([^"]+)"', html):
            if re.match(r"(https?:|mailto:|#)", target):
                continue
            path = (DOCS / target.split("#")[0]).resolve()
            if path.is_dir():
                path = path / "index.html"
            self.assertTrue(path.exists(), "broken local link: " + target)

    def test_home_page_explains_why_shows_the_format_and_links_install(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        for needle in ("Why TRACES.md?", "ts | tool | action | result",
                       'href="install/"', "failures are recorded", "traces validate",
                       "ghcr.io/maxont/traces", "<title>"):
            self.assertIn(needle, html)

    def test_install_page_has_humans_and_ai_sections(self):
        html = (DOCS / "install/index.html").read_text(encoding="utf-8")
        self.assertIn("For humans", html)
        self.assertIn("FOR YOUR AI", html)
        self.assertIn("Read %s/install and install traces for me." % SITE, html)
        self.assertIn("curl -fsSL %s/install.sh | bash" % SITE, html)
        self.assertIn("--dry-run", html)
        self.assertNotIn("@@", html)

    def test_install_script_is_filled_executable_and_points_at_this_repo(self):
        sh = DOCS / "install.sh"
        text = sh.read_text(encoding="utf-8")
        self.assertNotIn("@@", text)
        self.assertIn("https://github.com/MaxonT/traces.md", text)
        self.assertIn("command -v traces", text)
        self.assertTrue(sh.stat().st_mode & 0o111, "install.sh must be executable")
        self.assertIn("(3, 9)", text)


class PublishFilesTests(unittest.TestCase):
    def test_release_workflow_is_tag_triggered_and_publishes_wheel_sdist_and_image(self):
        text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn('tags: ["v*"]', text)
        self.assertIn("python -m build", text)
        self.assertIn("gh release", text)
        self.assertIn("image=ghcr.io/maxont/traces\n", text)
        self.assertNotIn("@@", text)

    def test_dockerfile_installs_the_package_and_runs_traces(self):
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY traces ./traces", text)
        self.assertIn('ENTRYPOINT ["traces"]', text)
        self.assertIn("ghcr.io/maxont/traces", text)

    def test_ci_workflow_runs_the_suite_and_validates_own_traces(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover", text)
        self.assertIn("traces validate --strict examples .trace", text)


if __name__ == "__main__":
    unittest.main()
