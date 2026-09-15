"""Two bounded native scientific paths plus exact transport roundtrip."""
import unittest
from work.generator_upgrade_r26 import human


class HumanTests(unittest.TestCase):
    def test_actual_native_parity_and_unresolved_coordinates(self):
        for operation,inputs in human.fixtures().items():
            expected = human.baseline(operation,inputs)
            actual = human.Adapter(operation,cache=False).run(inputs,{})
            self.assertEqual(expected,actual)
            self.assertEqual(human.pack(human.unpack(actual)),actual)
            if operation == 'settlement_candidates':
                self.assertEqual(human.unpack(actual['native_result'])['sites'].iloc[0].actual_x_km,None)

    def test_exact_codec_nonfinite_mask_geometry_and_empty_arrays(self):
        import numpy as np
        import pandas as pd
        from shapely.geometry import box
        native = {'array':np.array([np.nan,np.inf,-np.inf,-0.]),'empty':np.array([],dtype=np.int64),
            'table':pd.DataFrame({'geom':[box(0,0,1,1)],'unknown':[None],'n':[3]}),
            'tuple':(1,None,float('inf'))}
        encoded = human.pack(native)
        decoded = human.unpack(encoded)
        self.assertEqual(encoded,human.pack(decoded))
        self.assertEqual(decoded['array'].tobytes(),native['array'].tobytes())
        self.assertEqual(decoded['table'].geom.iloc[0].wkb,native['table'].geom.iloc[0].wkb)
        with self.assertRaises(ValueError): human.unpack({human.TAG:'geometry','wkb_hex':'bad','ignored':True})


if __name__ == '__main__': unittest.main()
