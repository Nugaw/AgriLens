"""Prompts + JSON schemas. Schemas go to Ollama's `format` so the model must return valid JSON."""

SYSTEM = """You are AgriLens, an offline agricultural assistant for farmers in Nepal. You help with plant symptoms, pesticide/fertilizer labels, farming documents and farm news.

RULES:
1. NEVER invent dosages, concentrations, mixing ratios, frequencies, pre-harvest intervals, PPE, target crops or pests.
2. A printed product label is the source of truth. Copy numbers, chemical names, units and percentages exactly.
3. If something is missing or unreadable, say so. Do not guess.
4. Mark evidence: OBSERVED (visible), EXTRACTED (read from label/document), INFERRED (tentative), UNKNOWN.
5. Never give a definite disease diagnosis from a photo alone; give possibilities with uncertainty.
6. Keep answers short and simple. A farmer will read (or listen to) them on a phone."""

NR = {"ne": "लेबलमा पढ्न सकिएन", "en": "Not readable from the provided image"}

LANG = {
    "ne": "भाषा: सरल नेपाली (देवनागरी), किसानले बुझ्ने सजिला शब्दमा। संख्या, रासायनिक नाम र एकाइ (जस्तै 20%, 5 ml/L) जस्ताको तस्तै राख्नुहोस्। JSON का key अंग्रेजीमै राख्नुहोस्, value नेपालीमा लेख्नुहोस्।",
    "en": "Language: simple English suitable for a farmer.",
}


def system(lang):
    return SYSTEM + "\n\n" + LANG.get(lang, LANG["en"])


def S(): return {"type": "string"}
def L(): return {"type": "array", "items": {"type": "string"}}
def obj(props): return {"type": "object", "properties": props, "required": list(props)}


EV = {"type": "string", "enum": ["OBSERVED", "EXTRACTED", "INFERRED", "UNKNOWN"]}
CONF = {"type": "string", "enum": ["Low", "Moderate", "High"]}

PLANT_SCHEMA = obj({
    "crop_detected": S(), "observed_symptoms": L(), "possible_causes": L(), "confidence": CONF,
    "disclaimer": S(), "recommended_next_steps": L(),
    "evidence": obj({"crop_detected": EV, "observed_symptoms": EV, "possible_causes": EV, "recommended_next_steps": EV}),
})
LABEL_SCHEMA = obj({
    "product_name": S(), "category": S(), "active_ingredient": S(), "npk_ratio": S(), "manufacturer": S(),
    "expiry_date": S(), "manufacture_date": S(), "batch_no": S(),
    "hazard_color": {"type": "string", "enum": ["red", "yellow", "blue", "green", "unknown"]},
    "target_pests_crops": L(), "dosage": S(), "mixing_ratio": S(), "pre_harvest_interval": S(),
    "ppe": L(), "warnings": L(), "nutrient_guide": S(), "farmer_summary": S(), "unreadable_fields": L(),
})
MATCH_SCHEMA = obj({
    "plant_problem": S(), "label_targets": L(),
    "match": {"type": "string", "enum": ["Match", "Possible mismatch", "Mismatch", "Unknown"]},
    "mismatch_risks": L(), "advice": S(),
})
NEWS_SCHEMA = obj({
    "category": {"type": "string", "enum": ["price", "weather", "scheme", "disease_pest", "technique", "other"]},
    "summary": S(), "key_points": L(), "farmer_relevance": S(),
})
LEARN_SCHEMA = obj({
    "what_it_is": S(), "used_for": L(), "how_it_works": S(),
    "how_to_use": L(), "safety": L(), "check_label": S(),
})

PLANT = 'Analyze this crop/plant photo. User note: "{note}". Describe only what is visible; list possible causes (not a diagnosis); suggest safe next steps (e.g. consult the local agriculture technician, isolate affected plants). No chemical doses.'
LABEL = ('These are the {side} of a {kind} product label. Read ONLY what is printed. For any field not printed or not readable write exactly "{nr}" '
         '(use an empty list for list fields and put the field name in unreadable_fields). hazard_color = colour of the toxicity triangle/band if visible, else "unknown". '
         'farmer_summary = 2 short sentences: what the product is + the single most important safety point; add no dose that is not printed.')
LEARN = ('Product: {name}. Active ingredient: {ai}. Type: {cat}. Targets printed on label: {targets}. '
         'Using general agricultural knowledge about this active ingredient (NOT the label), explain for a Nepali farmer: '
         'what_it_is (1-2 sentences); used_for (common crops/pests/diseases, max 4); how_it_works (1 sentence); '
         'how_to_use (general method only, e.g. foliar spray, best time of day; NO doses, concentrations, mixing ratios or intervals); '
         'safety (max 3 general points); check_label (one sentence: follow the printed label for the dose). '
         'If you are not sure what this product is, say so in what_it_is and leave the lists empty.')
MATCH = ('Image 1 shows a plant problem, image 2 is a product label. Compare the visible problem with the label\'s printed target pests/diseases/crops. '
         'Do NOT prescribe or give doses. If the label does not list targets, match = "Unknown".')
OCR = "Transcribe ALL text in this image exactly as written (Nepali and/or English). Keep line breaks. Output only the text, no comments."
DOC = ('Answer ONLY from the excerpts below. Cite pages like (पृष्ठ 3). If the answer is not in the excerpts reply exactly: "{nf}".\n\nEXCERPTS:\n{ctx}\n\nQUESTION: {q}')
DOC_NF = {"ne": "यो जानकारी कागजातमा भेटिएन।", "en": "I couldn't find this information in the document."}
DOC_SUMMARY = "Summarize this document for a farmer in at most 6 short bullet points. Use only facts in the text. Mention page numbers when useful.\n\nTEXT:\n{ctx}"
NEWS = ('Summarize this agriculture news for a Nepali farmer. Use ONLY facts in the text; add no numbers, prices or dates that are not present. '
        'summary = 2-3 short sentences; key_points = up to 3 short items; farmer_relevance = one sentence on who it matters to (no chemical advice).\n\nTITLE: {title}\nTEXT: {text}')
RECORD_CTX = "\n\nThe farmer is asking about this earlier {kind} result (JSON). Use it as context and do not contradict it:\n{data}"

QUALITY = {
    "ne": {"small": ("फोटो साना छ", "ठूलो/नजिकको फोटो लिनुहोस्"),
           "dark": ("फोटो धेरै अँध्यारो छ", "दिउँसो उज्यालोमा फोटो खिच्नुहोस्"),
           "blurry": ("फोटो धमिलो छ", "मोबाइल स्थिर समात्नुहोस् र नजिक जानुहोस्")},
    "en": {"small": ("Photo too small", "Use a larger or closer photo"),
           "dark": ("Photo too dark", "Take it in daylight"),
           "blurry": ("Photo blurry", "Hold steady and move closer")},
}
MSG = {
    "ne": {"badimg": "यो फोटो खोल्न सकिएन। JPG/PNG प्रयोग गर्नुहोस्।", "down": "AI (Ollama) चलिरहेको छैन। टर्मिनलमा `ollama serve` चलाउनुहोस्।",
           "empty": "कागजातमा पढ्न मिल्ने अक्षर भेटिएन।", "nodoc": "कागजात भेटिएन।", "toolarge": "फाइल धेरै ठूलो छ।"},
    "en": {"badimg": "Could not open this image. Use JPG/PNG.", "down": "AI (Ollama) is not running. Run `ollama serve`.",
           "empty": "No readable text found in the document.", "nodoc": "Document not found.", "toolarge": "File too large."},
}
