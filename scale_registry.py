import music21
print(f"music21 version: {music21.__version__}")

try:
    from music21 import scale, pitch
    print(f"music21.scale.AbstractScale available: {hasattr(scale, 'AbstractScale')}")
    
    if hasattr(scale, 'AbstractScale'):
        tonic_c = pitch.Pitch('C4')
        
        # メジャーペンタトニックのテスト
        try:
            abs_major_penta = scale.AbstractScale([0, 2, 4, 7, 9])
            print(f"AbstractMajorPentatonic created: {abs_major_penta}")
            concrete_major_penta = abs_major_penta.derive(tonic_c)
            print(f"Derived ConcreteMajorPentatonic: {concrete_major_penta}")
            if isinstance(concrete_major_penta, scale.ConcreteScale):
                print(f"  Pitches for C Major Pentatonic: {[p.nameWithOctave for p in concrete_major_penta.getPitches(tonic_c, tonic_c.transpose(12))]}")
            else:
                print(f"  derive() did not return a ConcreteScale for Major Pentatonic. Type: {type(concrete_major_penta)}")
        except Exception as e_maj_penta:
            print(f"Error testing Major Pentatonic with AbstractScale: {e_maj_penta}")

        # マイナーペンタトニックのテスト
        try:
            abs_minor_penta = scale.AbstractScale([0, 3, 5, 7, 10])
            print(f"AbstractMinorPentatonic created: {abs_minor_penta}")
            concrete_minor_penta = abs_minor_penta.derive(tonic_c)
            print(f"Derived ConcreteMinorPentatonic: {concrete_minor_penta}")
            if isinstance(concrete_minor_penta, scale.ConcreteScale):
                print(f"  Pitches for C Minor Pentatonic: {[p.nameWithOctave for p in concrete_minor_penta.getPitches(tonic_c, tonic_c.transpose(12))]}")
            else:
                print(f"  derive() did not return a ConcreteScale for Minor Pentatonic. Type: {type(concrete_minor_penta)}")
        except Exception as e_min_penta:
            print(f"Error testing Minor Pentatonic with AbstractScale: {e_min_penta}")
    else:
        print("music21.scale.AbstractScale is NOT available.")
        
except ImportError:
    print("Could not import music21.scale or music21.pitch")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
