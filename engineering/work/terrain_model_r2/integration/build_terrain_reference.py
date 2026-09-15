"""Official bounded terrain reference entry; no Diadem production authority."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

PACKAGE=Path(__file__).with_name("terrain_reference_r2")
sys.path.insert(0,str(PACKAGE))
import workflow


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe",type=Path,required=True)
    parser.add_argument("--expected-recipe-sha256",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args()
    if hashlib.sha256(workflow.read_bytes(args.recipe)).hexdigest()!=args.expected_recipe_sha256:
        raise ValueError("recipe changed since normal-workflow authorization")
    result=workflow.run(args.recipe,args.output,resume=args.resume,
                        expected_recipe_sha256=args.expected_recipe_sha256)
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
