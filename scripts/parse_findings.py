import json
import sys


def map_pylint_severity(message_type):
    severity_map = {
        "fatal": "CRITICAL",
        "error": "HIGH",
        "warning": "MEDIUM",
        "refactor": "LOW",
        "convention": "LOW",
        "info": "LOW"
    }

    return severity_map.get(message_type.lower(), "LOW")


def map_eslint_severity(severity):
    if severity == 2:
        return "HIGH"

    if severity == 1:
        return "MEDIUM"

    return "LOW"


def parse_pylint(data):
    findings = []

    for item in data:
        finding = {
            "file": item.get("path", ""),
            "line": item.get("line", 0),
            "rule": item.get("symbol", ""),
            "severity": map_pylint_severity(
                item.get("type", "info")
            ),
            "message": item.get("message", "")
        }

        findings.append(finding)

    return findings


def parse_eslint(data):
    findings = []

    for file_result in data:
        file_path = file_result.get("filePath", "")

        for item in file_result.get("messages", []):
            finding = {
                "file": file_path,
                "line": item.get("line", 0),
                "rule": item.get("ruleId") or "unknown",
                "severity": map_eslint_severity(
                    item.get("severity", 0)
                ),
                "message": item.get("message", "")
            }

            findings.append(finding)

    return findings


def load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def parse_findings(pylint_file=None, eslint_file=None):
    findings = []

    if pylint_file:
        pylint_data = load_json(pylint_file)
        findings.extend(parse_pylint(pylint_data))

    if eslint_file:
        eslint_data = load_json(eslint_file)
        findings.extend(parse_eslint(eslint_data))

    return findings


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python parse_findings.py "
            "<pylint.json> <eslint.json>"
        )
        sys.exit(1)

    pylint_file = sys.argv[1]
    eslint_file = sys.argv[2]

    findings = parse_findings(
        pylint_file,
        eslint_file
    )

    print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    main()