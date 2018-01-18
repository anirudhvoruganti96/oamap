#!/usr/bin/env python

# Copyright (c) 2017, DIANA-HEP
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# 
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# 
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import re
import json

import oamap.generator
import oamap.inference
import oamap.fillable

def toarrays(fillables):
    return dict((n, x[:]) for n, x in fillables.items())

################################################################ Python data, possibly made by json.load

def _fromdata_initialize(gen, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root):
    if isinstance(gen, oamap.generator.PrimitiveGenerator):
        fillables[gen.data].revert()
        forefront = len(fillables[gen.data])
        fillables_leaf_to_root.append(fillables[gen.data])

    elif isinstance(gen, oamap.generator.ListGenerator):
        _fromdata_initialize(gen.content, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root)
        fillables[gen.starts].revert()
        fillables[gen.stops].revert()
        assert len(fillables[gen.starts]) == len(fillables[gen.stops])
        forefront = len(fillables[gen.stops])
        fillables_leaf_to_root.append(fillables[gen.starts])
        fillables_leaf_to_root.append(fillables[gen.stops])

    elif isinstance(gen, oamap.generator.UnionGenerator):
        for x in gen.possibilities:
            _fromdata_initialize(x, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root)
        fillables[gen.tags].revert()
        fillables[gen.offsets].revert()
        assert len(fillables[gen.tags]) == len(fillables[gen.offsets])
        forefront = len(fillables[gen.tags])
        fillables_leaf_to_root.append(fillables[gen.tags])
        fillables_leaf_to_root.append(fillables[gen.offsets])

    elif isinstance(gen, oamap.generator.RecordGenerator):
        uniques = set(_fromdata_initialize(x, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root) for x in gen.fields.values())
        assert len(uniques) == 1
        forefront = list(uniques)[0]

    elif isinstance(gen, oamap.generator.TupleGenerator):
        uniques = set(_fromdata_initialize(x, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root) for x in gen.types)
        assert len(uniques) == 1
        forefront = list(uniques)[0]

    elif isinstance(gen, oamap.generator.PointerGenerator):
        if gen._internal and gen.target is generator and len(fillables[gen.positions]) != 0:
            raise TypeError("the root of a Schema may be the target of a Pointer, but if so, it can only be filled from data once")

        if gen not in pointers:
            pointers.append(gen)
        pointerobjs_keys.append(id(gen))
        targetids_keys.append(id(gen.target))

        if not gen._internal:
            _fromdata_initialize(gen.target, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root)
        fillables[gen.positions].revert()
        forefront = len(fillables[gen.positions])
        fillables_leaf_to_root.append(fillables[gen.positions])

    elif isinstance(gen, oamap.generator.ExtendedGenerator):
        forefront = _fromdata_initialize(gen.generic, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root)

    else:
        raise TypeError("unrecognized generator: {0}".format(repr(gen)))

    if isinstance(gen, oamap.generator.Masked):
        fillables[gen.mask].revert()
        # mask forefront overrides any other arrays
        forefront = len(fillables[gen.mask])
        fillables_leaf_to_root.append(fillables[gen.mask])

    return forefront

def _fromdata_forefront(gen, fillables, secondary=False):
    if not secondary and isinstance(gen, oamap.generator.Masked):
        # mask forefront overrides any other arrays
        return fillables[gen.mask].forefront()

    elif isinstance(gen, oamap.generator.PrimitiveGenerator):
        return fillables[gen.data].forefront()

    elif isinstance(gen, oamap.generator.ListGenerator):
        return fillables[gen.stops].forefront()

    elif isinstance(gen, oamap.generator.UnionGenerator):
        return fillables[gen.tags].forefront()

    elif isinstance(gen, oamap.generator.RecordGenerator):
        for x in gen.fields.values():
            return _fromdata_forefront(x, fillables)

    elif isinstance(gen, oamap.generator.TupleGenerator):
        for x in gen.types:
            return _fromdata_forefront(x, fillables)

    elif isinstance(gen, oamap.generator.PointerGenerator):
        return len(pointerobjs[id(gen)])

    elif isinstance(gen, oamap.generator.ExtendedGenerator):
        return _fromdata_forefront(gen.generic, fillables)

def _fromdata_unionnullable(union):
    for possibility in union.possibilities:
        if isinstance(possibility, oamap.generator.Masked):
            return True
        elif isinstance(possibility, oamap.generator.UnionGenerator):
            return _fromdata_unionnullable(possibility)
    return False

def _fromdata_fill(obj, gen, fillables, targetids, pointerobjs, at, pointerat):
    if id(gen) in targetids:
        targetids[id(gen)][id(obj)] = (_fromdata_forefront(gen, fillables), obj)

    if obj is None:
        if isinstance(gen, oamap.generator.Masked):
            fillables[gen.mask].append(gen.maskedvalue)
            return   # only mask is filled
        elif isinstance(gen, oamap.generator.UnionGenerator) and _fromdata_unionnullable(gen):
            pass     # mask to fill is in a Union possibility
        elif isinstance(gen, oamap.generator.ExtendedGenerator) and isinstance(gen.generic, oamap.generator.Masked):
            _fromdata_fill(obj, gen.generic, fillables, targetids, pointerobjs, at, pointerat)
            return   # filled the generic generator's mask
        else:
            raise TypeError("cannot fill None where expecting type {0} at {1}".format(gen.schema, at))

    # obj is not None (except for the Union case)
    if isinstance(gen, oamap.generator.Masked):
        fillables[gen.mask].append(_fromdata_forefront(gen, fillables, secondary=True))

    if isinstance(gen, oamap.generator.PrimitiveGenerator):
        fillables[gen.data].append(obj)

    elif isinstance(gen, oamap.generator.ListGenerator):
        start = stop = _fromdata_forefront(gen.content, fillables)
        try:
            if isinstance(obj, dict) or (isinstance(obj, tuple) and hasattr(obj, "_fields")):
                raise TypeError
            iter(obj)
        except TypeError:
            raise TypeError("cannot fill {0} where expecting type {1} at {2}".format(repr(obj), gen.schema, at))
        else:
            for x in obj:
                _fromdata_fill(x, gen.content, fillables, targetids, pointerobjs, at + (stop - start,), pointerat)
                stop += 1

        fillables[gen.starts].append(start)
        fillables[gen.stops].append(stop)

    elif isinstance(gen, oamap.generator.UnionGenerator):
        tag = None
        for i, possibility in enumerate(gen.possibilities):
            if obj in possibility.schema:
                tag = i
                break
        if tag is None:
            raise TypeError("cannot fill {0} where expecting type {1} at {2}".format(repr(obj), gen.schema, at))

        offset = _fromdata_forefront(possibility, fillables)
        _fromdata_fill(obj, possibility, fillables, targetids, pointerobjs, at + ("tag" + repr(tag),), pointerat)

        fillables[gen.tags].append(tag)
        fillables[gen.offsets].append(offset)

    elif isinstance(gen, oamap.generator.RecordGenerator):
        if isinstance(obj, dict):
            for n, x in gen.fields.items():
                if n not in obj:
                    raise TypeError("cannot fill {0} because its {1} field is missing at {2}".format(repr(obj), repr(n), at))
                _fromdata_fill(obj[n], x, fillables, targetids, pointerobjs, at + (n,), pointerat)
        else:
            for n, x in gen.fields.items():
                if not hasattr(obj, n):
                    raise TypeError("cannot fill {0} because its {1} field is missing at {2}".format(repr(obj), repr(n), at))
                _fromdata_fill(getattr(obj, n), x, fillables, targetids, pointerobjs, at + (n,), pointerat)

    elif isinstance(gen, oamap.generator.TupleGenerator):
        for i, x in enumerate(gen.types):
            try:
                v = obj[i]
            except (TypeError, IndexError):
                raise TypeError("cannot fill {0} because it does not have a field {1} at {2}".format(repr(obj), i, at))
            else:
                _fromdata_fill(v, x, fillables, targetids, pointerobjs, at + (i,), pointerat)

    elif isinstance(gen, oamap.generator.PointerGenerator):
        # Pointers will be set after we see all the target values
        pointerobjs[id(gen)].append(obj)
        if id(gen) not in pointerat:
            pointerat[id(gen)] = at

    elif isinstance(gen, oamap.generator.ExtendedGenerator):
        _fromdata_fill(gen.degenerate(obj), gen.generic, fillables, targetids, pointerobjs, at, pointerat)

def _fromdata_finish(fillables, pointers, pointerobjs, targetids, pointerat, pointer_fromequal, fillables_leaf_to_root):
    # do the pointers after everything else
    for pointer in pointers:
        while len(pointerobjs[id(pointer)]) > 0:
            pointerobjs2 = {id(pointer): []}
            for obj in pointerobjs[id(pointer)]:
                if id(obj) in targetids[id(pointer.target)] and targetids[id(pointer.target)][id(obj)][1] == obj:
                    # case 1: an object in the target *is* the object in the pointer (same ids)
                    position, _ = targetids[id(pointer.target)][id(obj)]

                else:
                    position = None
                    if pointer_fromequal:
                        # fallback to quadratic complexity search
                        for key, (pos, obj2) in targetids[id(pointer.target)].items():
                            if obj == obj2:
                                position = pos
                                break

                    if position is not None:
                        # case 2: an object in the target *is equal to* the object in the pointer (only check if pointer_fromequal)
                        pass

                    else:
                        # case 3: the object was not found; it must be added to the target (beyond indexes where it can be found)
                        _fromdata_fill(obj, pointer.target, fillables, targetids, pointerobjs2, pointerat[id(pointer)], pointerat)
                        position, _ = targetids[id(pointer.target)][id(obj)]

                # every obj in pointerobjs[id(pointer)] gets *one* append
                fillables[pointer.positions].append(position)

            pointerobjs[id(pointer)] = pointerobjs2[id(pointer)]

    # success! (we're still here)
    for fillable in fillables_leaf_to_root:
        fillable.update()

def fromdata(value, generator=None, fillables=None, pointer_fromequal=False):
    if generator is None:
        generator = oamap.inference.fromdata(value).generator()

    if not isinstance(generator, oamap.generator.Generator):
        generator = generator.generator()

    if fillables is None:
        fillables = oamap.fillable.arrays(generator)

    pointers = []
    pointerobjs_keys = []
    targetids_keys = []
    fillables_leaf_to_root = []
    
    _fromdata_initialize(generator, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root)

    if _fromdata_forefront(generator, fillables) != 0 and not isinstance(generator, oamap.generator.ListGenerator):
        raise TypeError("non-Lists can only be filled from data once")

    pointerat = {}
    targetids = dict((x, {}) for x in targetids_keys)
    pointerobjs = dict((x, []) for x in pointerobjs_keys)

    _fromdata_fill(value, generator, fillables, targetids, pointerobjs, (), pointerat)
    _fromdata_finish(fillables, pointers, pointerobjs, targetids, pointerat, pointer_fromequal, fillables_leaf_to_root)

    return fillables

def fromiterdata(values, generator=None, fillables=None, pointer_fromequal=False, until=None):
    if generator is None:
        generator = oamap.inference.fromdata(values).generator()
    if not isinstance(generator, oamap.generator.ListGenerator):
        raise TypeError("non-Lists can only be filled from data once")

    if not isinstance(generator, oamap.generator.Generator):
        generator = generator.generator()

    if fillables is None:
        fillables = oamap.fillable.arrays(generator)

    pointers = []
    pointerobjs_keys = []
    targetids_keys = []
    fillables_leaf_to_root = []
    
    _fromdata_initialize(generator, generator, fillables, pointers, pointerobjs_keys, targetids_keys, fillables_leaf_to_root)

    pointerat = {}
    targetids = dict((x, {}) for x in targetids_keys)
    pointerobjs = dict((x, []) for x in pointerobjs_keys)

    for value in values:
        _fromdata_fill(value, generator, fillables, targetids, pointerobjs, (), pointerat)
        if until is not None and until(fillables):
            break

    _fromdata_finish(fillables, pointers, pointerobjs, targetids, pointerat, pointer_fromequal, fillables_leaf_to_root)

    return fillables

################################################################ helper functions for JSON-derived data and iterables

def fromjson(value, generator=None, fillables=None, pointer_fromequal=False):
    return fromdata(oamap.inference.jsonconventions(value), generator=generator, fillables=fillables, pointer_fromequal=pointer_fromequal)

def fromjsonfile(value, generator=None, fillables=None, pointer_fromequal=False):
    return fromdata(oamap.inference.jsonconventions(json.load(value)), generator=generator, fillables=fillables, pointer_fromequal=pointer_fromequal)

def fromjsonstring(value, generator=None, fillables=None, pointer_fromequal=False):
    return fromdata(oamap.inference.jsonconventions(json.loads(value)), generator=generator, fillables=fillables, pointer_fromequal=pointer_fromequal)

def fromjsonfilestream(values, generator=None, fillables=None, pointer_fromequal=False, until=None):
    def iterator():
        j = json.JSONDecoder()
        buf = ""
        while True:
            try:
                obj, i = j.raw_decode(buf)
            except ValueError:
                extra = values.read(8192)
                if len(extra) == 0:
                    break
                else:
                    buf = buf.lstrip() + extra
            else:
                yield oamap.inference.jsonconventions(obj)
                buf = buf[i:].lstrip()

    return fromiterdata(iterator(), generator=generator, fillables=fillables, pointer_fromequal=pointer_fromequal, until=until)

def fromjsonstream(values, generator=None, fillables=None, pointer_fromequal=False, until=None):
    def iterator():
        j = json.JSONDecoder()
        index = 0
        while True:
            try:
                obj, i = j.raw_decode(values[index:])
            except ValueError:
                break
            yield oamap.inference.jsonconventions(obj)
            _, index = fromjsonstream._pattern.match(values, index + i).span()

    return fromiterdata(iterator(), generator=generator, fillables=fillables, pointer_fromequal=pointer_fromequal, until=until)

fromjsonstream._pattern = re.compile("\s*")
