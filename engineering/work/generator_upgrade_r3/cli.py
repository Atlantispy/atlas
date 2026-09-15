"""Public bounded JSON recipe runner; exclusive outputs, exact restart binding."""
import argparse
import json
from pathlib import Path
from . import storage, provenance
from .pipeline import run
from .reference import recipe as reference_recipe


def execute(recipe,run_id,*,stop_after=None,resume=None):
    identity,source_hash=provenance.source_identity()
    result=run(recipe,stop_after=stop_after,resume=resume,source_sha256=source_hash)
    if provenance.source_identity()!=(identity,source_hash):raise ValueError('source changed during generation')
    checkpoint=storage.checkpoint(result['state'],recipe_sha256=storage.sha(storage.encoded(recipe)),source_sha256=source_hash)
    root,receipt=storage.save_reference(run_id,recipe=recipe,result=result,checkpoint_record=checkpoint,
        evidence={'source_identity':identity,'source_sha256':source_hash,'recipe_sha256':storage.sha(storage.encoded(recipe)),
            'verification':'actual connected run and exclusive artefact readback; not independent final test acceptance'})
    return root,receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--reference',action='store_true');source.add_argument('--recipe',type=Path)
    p.add_argument('--run-id',required=True);p.add_argument('--stop-after',type=int);p.add_argument('--resume',type=Path)
    args=p.parse_args()
    recipe=reference_recipe() if args.reference else storage.read_json(args.recipe.absolute())
    resume=storage.read_json(args.resume.absolute()) if args.resume else None
    root,receipt=execute(recipe,args.run_id,stop_after=args.stop_after,resume=resume)
    print(json.dumps({'status':'SAVED_AND_READ_BACK','path':str(root),'files':receipt['files'],
        'production_installed':False,'canon_changed':False}))


if __name__=='__main__':main()
