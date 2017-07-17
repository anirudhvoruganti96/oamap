#!/usr/bin/env python

# Copyright 2017 DIANA-HEP
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from collections import namedtuple

from rolup.typesystem import *
from rolup.typesystem.columns import type2columns
from rolup.typesystem.columns import columns2type

class TestTypesColumns(unittest.TestCase):
    def runTest(self):
        pass

    def test_primitives(self):
        print type2columns(float64, "x")
        print type2columns(List(float64), "x")
        print type2columns(List(List(float64)), "x")
        print type2columns(Record(x=int8, y=float64), "x")
        print type2columns(List(Record(x=int8, y=float64)), "x")
        print type2columns(Record(x=int8, y=List(float64)), "x")
        print type2columns(List(Record(x=int8, y=List(float64))), "x")