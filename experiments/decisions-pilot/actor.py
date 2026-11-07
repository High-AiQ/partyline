"""Run Microsoft's GUI-Actor on synthetic frames, one BF16 example at a time."""
import json
import time
from pathlib import Path

import torch
from gui_actor.inference import inference
from gui_actor.modeling import Qwen2VLForConditionalGenerationWithPointer
from transformers import Qwen2VLProcessor

ROOT = Path(__file__).parent
OUT = ROOT / 'generated'
MODEL = 'microsoft/GUI-Actor-2B-Qwen2-VL'


def main():
    start = time.perf_counter()
    processor = Qwen2VLProcessor.from_pretrained(MODEL)
    model = Qwen2VLForConditionalGenerationWithPointer.from_pretrained(
        MODEL, torch_dtype=torch.bfloat16, device_map='cuda:0', attn_implementation='eager').eval()
    load_seconds = time.perf_counter() - start
    torch.cuda.reset_peak_memory_stats()
    rows = json.loads((OUT / 'dataset.json').read_text())['choices']
    results = []
    for row in rows:
        conversation = [{'role': 'system', 'content': [{'type': 'text', 'text':
            'You are a GUI agent. Given a task and screenshot, identify the target.'}]},
            {'role': 'user', 'content': [{'type': 'image', 'image': str(OUT / row['image'])},
                                         {'type': 'text', 'text': row['intent']}]}]
        start = time.perf_counter()
        prediction = inference(conversation, model, processor.tokenizer, processor,
                               use_placeholder=True, topk=1)
        x, y = prediction['topk_points'][0]
        x, y = float(x) * 800, float(y) * 600
        matches = [c['id'] for c in row['candidates'] if c['bounds'][0] <= x < c['bounds'][0] + c['bounds'][2]
                   and c['bounds'][1] <= y < c['bounds'][1] + c['bounds'][3]]
        results.append({'id': row['id'], 'point': [x, y],
                        'choice': matches[0] if len(matches) == 1 else 'abstain',
                        'seconds': time.perf_counter() - start})
        (OUT / 'actor.json').write_text(json.dumps({'load_seconds': load_seconds,
            'peak_vram_bytes': torch.cuda.max_memory_reserved(), 'results': results}, indent=2))
        print(row['id'], flush=True)


if __name__ == '__main__':
    main()
