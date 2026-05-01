import sys
sys.path.insert(0, r'c:\Grom_OCR\python')
from ocr_agent import get_best_result, should_accept_result

ocr_results = {
  'doctr': {'text': 'UEO4013', 'avg_conf': 85.0, 'score': 126.5, 'pattern': 'Antigo', 'region': 'center_lower_focus'},
  'rapidocr': {'text': 'OFO8819', 'avg_conf': 81.8, 'score': 123.5, 'pattern': 'Antigo', 'region': 'center_lower_focus'},
  'easyocr': {'text': 'OGD0019', 'avg_conf': 52.3, 'score': 104.5, 'pattern': 'Antigo', 'region': 'lower_wide_focus'}
}

best_engine, best_res = get_best_result(ocr_results)
print("Engine:", best_engine)
print("Best:", best_res)

accepted, reason = should_accept_result(best_res)
print("Accepted:", accepted)
print("Reason:", reason)
