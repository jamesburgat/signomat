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

    learned_speed = mapper.map_label("regulatory_maximum_speed_limit_45_g3")
    assert learned_speed.category_id == "speed_limit"
    assert learned_speed.specific_label == "regulatory_maximum_speed_limit_45_g3"

    learned_stop = mapper.map_label("regulatory_stop_g1")
    assert learned_stop.category_id == "stop"
    assert learned_stop.specific_label == "regulatory_stop_g1"

    learned_warning = mapper.map_label("warning_roadworks_g1")
    assert learned_warning.category_id == "warning_general"
    assert learned_warning.specific_label == "warning_roadworks_g1"

    detector_only = mapper.map_label("sign")
    assert detector_only.category_id == "sign"

    unknown = mapper.map_label("mystery_sign")
    assert unknown.category_id == "unknown_sign"
