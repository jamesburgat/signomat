ALTER TABLE detections ADD COLUMN classification_state TEXT NOT NULL DEFAULT 'unclassified';

UPDATE detections
SET classification_state = CASE
  WHEN COALESCE(raw_classifier_label, '') = '' THEN 'unclassified'
  WHEN COALESCE(raw_classifier_label, '') = 'unknown_sign'
    OR COALESCE(category_label, '') = 'unknown_sign' THEN 'classification_unknown'
  ELSE 'machine_classified'
END;

UPDATE detections
SET review_state = 'unreviewed'
WHERE review_state IN ('machine_classified', 'classification_unknown');
