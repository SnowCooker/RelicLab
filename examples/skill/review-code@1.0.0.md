---
{
  "schema_version": "1.0",
  "id": "review-code",
  "kind": "skill",
  "version": "1.0.0",
  "name": "Review Code",
  "trigger": "When reviewing a change",
  "tools": [
    {
      "name": "read_file",
      "description": "Read a workspace-relative source file.",
      "input_schema": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string"
          }
        },
        "required": [
          "path"
        ],
        "additionalProperties": false
      }
    }
  ]
}
---
Inspect the changed code and its callers. Report actionable defects.
