import spacy
from collections import defaultdict
import os
nlp = spacy.load(os.path.join(os.path.dirname(__file__), "..", "model", "model-best"))


def classify_chunks(chunks, threshold=0.5):
    results = defaultdict(list)
    for _, chunk in chunks:
        doc = nlp(chunk)
        scores = doc.cats
        best_label = max(scores, key=scores.get)
        if scores[best_label] >= threshold:
            results[best_label].append(chunk)

    final_output = {}
    all_labels = [
        "SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION", "PROJECTS",
        "CERTIFICATIONS", "AWARDS", "ACCOMPLISHMENTS", "INTERESTS", "LANGUAGES"
    ]
    for label in all_labels:
        final_output[label] = "\n\n".join(results.get(label, [])).strip()
    return final_output
