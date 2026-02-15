# test_import.py
try:
    import golfgen.config
    print("✅ golfgen.config imported successfully!")
    print("golfgen.config.__file__ =", golfgen.config.__file__)
except ModuleNotFoundError as e:
    print("❌ Module error:", e)