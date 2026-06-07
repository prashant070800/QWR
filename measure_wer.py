import jiwer

# Ground truth vs actual transcriptions from recent calls
data = [
    {
        "ground_truth": "Yeah I think can you tell me more about are you jaxl com you know",
        "hypothesis": "Yeah, I think can you tell me more about are you are you jackal.com you know?"
    },
    {
        "ground_truth": "Yeah I think Think is better",
        "hypothesis": "Yeah, I think pink is better."
    },
    {
        "ground_truth": "What does your company do can you tell me more about your company",
        "hypothesis": "What your company do? Can you tell me more about your company?"
    },
    {
        "ground_truth": "No I think that's it I just want to know and I got to know about you guys I think that is much",
        "hypothesis": "No, I think that's it. I just want to know and I got to know much you guys. I think that is much"
    },
    {
        "ground_truth": "Yeah I want to know more about like what products you work on",
        "hypothesis": "Yeah, I want to know more about like what products you work on?"
    },
    {
        "ground_truth": "No I think that is quite good and I will learn more about it",
        "hypothesis": "No, I think that is quite good and I will learn more about it."
    }
]

# Standardize: remove punctuation and lowercase
transform = jiwer.Compose([
    jiwer.ToLowerCase(),
    jiwer.RemovePunctuation(),
    jiwer.RemoveWhiteSpace(replace_by_space=True),
    jiwer.RemoveMultipleSpaces(),
    jiwer.Strip(),
])

ground_truths = [transform(d["ground_truth"]) for d in data]
hypotheses = [transform(d["hypothesis"]) for d in data]

error_rate = jiwer.wer(ground_truths, hypotheses)

word_count = sum(len(gt.split()) for gt in ground_truths)

print(f"Total Words Tested: {word_count}")
print(f"Word Error Rate (WER): {error_rate * 100:.2f}%")
print("\n--- Detailed Breakdown ---")
for i, d in enumerate(data):
    gt_transformed = transform(d["ground_truth"])
    hyp_transformed = transform(d["hypothesis"])
    wer_item = jiwer.wer(gt_transformed, hyp_transformed)
    print(f"Turn {i+1}:")
    print(f"  Truth: {gt_transformed}")
    print(f"  Hyp:   {hyp_transformed}")
    print(f"  WER:   {wer_item * 100:.2f}%")
    print()
