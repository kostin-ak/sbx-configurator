import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from sbx.lint import has_errors, lint_config, summarize

ROOT = Path(__file__).resolve().parents[1]


def make_config(tmp: Path) -> Path:
    target = tmp / "config"
    shutil.copytree(ROOT / "config", target)
    return target


class LintTests(unittest.TestCase):
    def test_example_config_has_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            issues = lint_config(config)
            errors = [issue for issue in issues if issue.level == "error"]
            self.assertEqual(errors, [], [issue.render() for issue in issues])

    def test_unknown_category_rule_set_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            path = config / "routing/categories.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["categories"][0]["rules"].append({"rule_set": ["missing-set"]})
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            issues = lint_config(config)
            self.assertTrue(any(issue.code == "category-rule-set" for issue in issues), [i.render() for i in issues])
            self.assertTrue(has_errors(issues))

    def test_unknown_policy_category_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            path = config / "routing/policies.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["policies"][0]["categories"].append("nope")
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            issues = lint_config(config)
            self.assertTrue(any(issue.code == "policy-category" for issue in issues), [i.render() for i in issues])

    def test_unknown_group_member_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            path = config / "routing/groups.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["groups"]["Personal"]["members"].append("ghost")
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            issues = lint_config(config)
            self.assertTrue(any(issue.code == "group-member" for issue in issues), [i.render() for i in issues])

    def test_duplicate_address_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            path = config / "routing/devices.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["devices"]["Clone"] = {"ipv4": data["devices"]["Laptop"]["ipv4"]}
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            issues = lint_config(config)
            self.assertTrue(any(issue.code == "duplicate-address" for issue in issues), [i.render() for i in issues])
            self.assertFalse(has_errors(issues))

    def test_invalid_selector_regex_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            path = config / "selectors.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["templates"].append({"name": "broken", "tag": "Broken", "type": "selector", "filter": "(", "regex": True})
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            issues = lint_config(config)
            self.assertTrue(any(issue.code == "selector-regex" for issue in issues), [i.render() for i in issues])

    def test_invalid_transform_regex_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            path = config / "subscriptions.d/10-example.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data.setdefault("transforms", []).append({"action": "rename", "pattern": "(", "replacement": ""})
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            issues = lint_config(config)
            self.assertTrue(any(issue.code == "transform-regex" for issue in issues), [i.render() for i in issues])

    def test_summary_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            stats = summarize(lint_config(config))
            self.assertEqual(stats["errors"], 0)


if __name__ == "__main__":
    unittest.main()