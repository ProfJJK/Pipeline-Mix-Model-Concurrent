"""The connector must not make its own maintenance depend on a running pipeline."""
from cochem_pipeline.server import create_server


def test_instructions_scope_pipeline_authority_to_submitted_jobs():
    instructions = create_server(None).instructions
    assert 'For code changes, list configured projects' not in instructions
    assert 'Only for work explicitly submitted through this pipeline' in instructions
    assert 'Direct local maintenance of the pipeline itself does not require these tools' in instructions
    assert 'only its verified terminal result establishes completion of that submitted job' in instructions
