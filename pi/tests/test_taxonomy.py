from pathlib import Path

from signomat_pi.inference_service.taxonomy import TaxonomyMapper


def test_taxonomy_maps_specific_and_grouped_labels():
    mapper = TaxonomyMapper(Path("pi/config/taxonomy.yaml"))

    stop = mapper.map_label("stop")
    assert stop.category_id == "stop"
    assert stop.specific_label == "stop"

    speed = mapper.map_label("speed_limit_35")
    assert speed.category_id == "speed_limit"
    assert speed.specific_label == "speed_limit_35"

    unknown = mapper.map_label("mystery_sign")
    assert unknown.category_id == "unknown_sign"

