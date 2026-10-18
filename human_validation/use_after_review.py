# Run in your benchmark notebook AFTER loading A, B, RULES, bt and OUT.
# Put the proposal CSV in PACKAGE and review it in Excel first.
PROPOSALS = PACKAGE / 'adjudication_worklist_ai_proposals.csv'
work = bt.read_csv(PROPOSALS)
approved = work.human_review_status.str.strip().str.casefold().eq('approved')
if work.loc[approved, 'human_reviewer'].str.strip().eq('').any():
    raise ValueError('Enter the actual human reviewer for approved decisions.')
reviewed = work.copy()
reviewed.loc[~approved, 'final_label'] = ''
reviewed.loc[approved, 'adjudicator'] = (
    reviewed.loc[approved, 'human_reviewer'] + ' (reviewed AI-assisted proposal)'
)
WORK = OUT / 'adjudication_worklist_human_reviewed.csv'
reviewed.to_csv(WORK, index=False)
gold = bt.build_gold(A, B, RULES, reviewed)
gold.to_csv(OUT / 'consensus_and_adjudicated_labels.csv', index=False)
print('Human-reviewed proposals accepted:', int(approved.sum()))
print('Unreviewed proposals kept out of benchmark:', int((~approved).sum()))
# Continue with source/split loading and AI evaluation cells.
# Do not rerun the original worklist-generation cell on this file.
