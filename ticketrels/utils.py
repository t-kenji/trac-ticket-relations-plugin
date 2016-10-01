# -*- coding: utf-8 -*-

def text2list(text):
    converted = set([])
    if text:
        raw_list = text.replace(',', ' ').split()
        try:
            converted = set([int(num) for num in raw_list])
        except ValueError:
            pass

    return converted

def list2text(lst):
    return u', '.join(str(i) for i in sorted(lst))

def sorted_refs(orig_text, extra_refs):
    refs = text2list(orig_text)
    refs.update(extra_refs)
    return list2text(refs)
