"""Static artifact examples for the secure V3 renderer."""

from __future__ import annotations

from vanna import ArtifactComponent, UiComponent


def create_static_html_artifact() -> UiComponent:
    """Return sanitized HTML content with no executable behavior."""

    artifact = ArtifactComponent(
        content=(
            '<article class="summary">'
            "<h2>Quarterly summary</h2>"
            "<p>Revenue increased while support volume remained stable.</p>"
            "<table><thead><tr><th>Region</th><th>Revenue</th></tr></thead>"
            "<tbody><tr><td>EMEA</td><td>1200</td></tr></tbody></table>"
            "</article>"
        ),
        artifact_type="html",
        title="Static quarterly summary",
        description="Sanitized static content rendered in an empty sandbox.",
        editable=False,
        fullscreen_capable=True,
        external_renderable=False,
    )
    return UiComponent(rich_component=artifact)


def create_javascript_source_artifact() -> UiComponent:
    """Return JavaScript as inert source text, never executable content."""

    artifact = ArtifactComponent(
        content='console.log("This text is displayed but never executed.");',
        artifact_type="javascript",
        title="JavaScript source",
        description="V3 renders JavaScript artifact types as escaped source text.",
        editable=False,
        fullscreen_capable=False,
        external_renderable=False,
    )
    return UiComponent(rich_component=artifact)


def main() -> None:
    """Print the two payloads for local inspection."""

    for component in (
        create_static_html_artifact(),
        create_javascript_source_artifact(),
    ):
        artifact = component.rich_component
        print(f"{artifact.title}: {artifact.artifact_type}")
    print("Artifacts remain static; charts use the declarative ChartSpec protocol.")


if __name__ == "__main__":
    main()
