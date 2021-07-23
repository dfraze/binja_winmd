#!/usr/bin/env python3
import json
import codecs
import sys
import logging
from binaryninja.architecture import Architecture
from binaryninja.platform import Platform
from binaryninja.typelibrary import TypeLibrary
from binaryninja.enums import StructureVariant
from binaryninja.types import (Type, Pointer, Structure, Enumeration, Function)
from argparse import ArgumentParser
from pathlib import Path

typelib = TypeLibrary.new(Architecture["x86_64"], "Win32")
typelib.add_platform(Platform["windows-x86_64"])
arch = Architecture["x86_64"]
assert arch is not None
altnames = set()

def kind_to_bn_type(kind):
  if kind["Kind"] == "Native":
    return get_bn_type_from_name(kind["Name"])
  if kind["Kind"] == "ApiRef":
    return typelib.get_named_type(kind["Name"])

def get_bn_type_from_name(name):
  if name == "Byte":
    return Type.int(1, sign=False)
  elif name == "SByte":
    return Type.int(1)
  elif name == "Char":
    return Type.char()
  elif name == "UInt16":
    return Type.int(2, sign=False)
  elif name == "Int16":
    return Type.int(2)
  elif name == "Int64":
    return Type.int(8)
  elif name == "UInt32":
    return Type.int(4, sign=False)
  elif name == "UInt64":
    return Type.int(8, sign=False)
  elif name == "Int32":
    return Type.int(4)
  elif name == "Single":
    return Type.float(4)
  elif name == "Double":
    return Type.float(8)
  elif name == "UIntPtr":
    return Type.pointer(Type.int(8, sign=False), arch=arch)
  elif name == "IntPtr":
    return Type.pointer(Type.int(8, sign=True), arch=arch)
  elif name == "Void":
    return Type.void()
  elif name == "Boolean":
    return Type.bool()
  elif name == "Guid":
    #FIXME
    return Type.void()
  else:
    print(f"Unhandled Native Type: {name}")
    sys.exit(-1)

def handle_json_type(t):
  if t["Kind"] == "Native":
    return get_bn_type_from_name(t["Name"])
  if t["Kind"] == "PointerTo":
    return Type.pointer(handle_json_type(t["Child"]), arch=arch)
  if t["Kind"] == "Array":
    if t["Shape"]:
      return Type.array(handle_json_type(t["Child"]), int(t["Shape"]["Size"]))
    else:
      return Type.pointer(handle_json_type(t["Child"]), arch=arch)
  if t["Kind"] == "ApiRef":
    return Type.named_type_reference(name=t["Name"])
  if t["Kind"] == "Struct":
    for nested_type in t["NestedTypes"]:
      typelib.add_named_type(nested_type["Name"], handle_json_type(nested_type))
    new_struct = Structure()
    for field in t["Fields"]:
      child_type = handle_json_type(field["Type"])
      new_struct.append(type=child_type, name=field["Name"])
    return new_struct
  if t["Kind"] == "LPArray":
    return Type.pointer(handle_json_type(t["Child"]), arch=arch)
  if t["Kind"] == "Union":
    for nested_type in t["NestedTypes"]:
      typelib.add_named_type(nested_type["Name"], handle_json_type(nested_type))
    new_union = Structure(type=StructureVariant.UnionStructureType)
    for field in t["Fields"]:
      new_union.append(type=handle_json_type(field["Type"]), name=field["Name"])
    return new_union
  if t["Kind"] == "MissingClrType":
    return Type.void()
  else:
    print(f"Unhandled type: {t}")
    sys.exit(0)

def create_bn_type_from_json(t):
  if t["Kind"] == "NativeTypedef":
    new_typedef = handle_json_type(t["Def"])
    typelib.add_named_type(t["Name"], new_typedef)
  elif t["Kind"] == "Enum":
    with Enumeration().builder(typelib, t["Name"]) as new_enum:
      for member in t["Values"]:
        new_enum.append(member["Name"], int(member["Value"]))
  elif t["Kind"] == "Struct":
    real_new_type = handle_json_type(t)
    typelib.add_named_type(t["Name"], real_new_type)
  elif t["Kind"] == "FunctionPointer":
    with Pointer(arch=arch).builder(typelib, t["Name"]) as pointer:
      pointer.target = Function(handle_json_type(t["ReturnType"]))
      for param in t["Params"]:
        pointer.target.append(handle_json_type(param["Type"]), param["Name"])
  elif t["Kind"] == "Com":
    with Structure().builder(typelib, t["Name"]) as new_struct:
      for method in t["Methods"]:
        func = Function(handle_json_type(method["ReturnType"]))
        for param in method["Params"]:
          func.append(handle_json_type(param["Type"]), param["Name"])
        new_struct.append(type=Type.pointer(func, arch=arch), name=method["Name"])
  elif t["Kind"] == "ComClassID":
    return None
  elif t["Kind"] == "Union":
    typelib.add_named_type(t["Name"], handle_json_type(t))
    return None
  else:
    print(f"Found unknown type kind: {t['Kind']}")


def do_it(in_dir, out_file):
  p = Path(in_dir)

  files = p.glob("*.json")

  api_namespaces = {}
  for file in files:
    api_namespaces[file.stem] = json.load(codecs.open(file, "r", "utf-8-sig"))

  logging.info("Making a bunch of ..")
  i = 1
  for namespace in api_namespaces:
    metadata = api_namespaces[namespace]
    logging.debug(f"+++ Processing namespace {namespace} ({i} of {len(api_namespaces)})")
    i+=1
    types = metadata["Types"]
    for t in types:
      create_bn_type_from_json(t)

  logging.info("Alright, now let's do some functions")

  i = 1
  func_count = 0
  for namespace in api_namespaces:
    metadata = api_namespaces[namespace]
    logging.debug(f"+++ Processing namespace {namespace} ({i} of {len(api_namespaces)})")
    i+=1
    funcs = metadata["Functions"]
    for f in funcs:
      altnames.add(f["DllImport"])
      with Function(handle_json_type(f["ReturnType"])).builder(typelib, f["Name"]) as func:
        for param in f["Params"]:
          func.append(handle_json_type(param["Type"]), param["Name"])
      func_count+=1

  for dll in altnames:
    logging.info(f"Adding {dll} to alt names.")
    typelib.add_alternate_name(f"{dll}.dll".lower())

  typelib.finalize()
  typelib.write_to_file(out_file)

if __name__ == "__main__":
  _args = ArgumentParser(description='Build a typelib from win32json project')
  _args.add_argument("win32json_api_directory")
  _args.add_argument("output_dir")
  _args.add_argument("-v", action="count", help="Increase logging verbosity. Can specify multiple times.")
  args = _args.parse_args()
  if args.v != None:
    logging.basicConfig(level=max(30-(args.v * 10), 0))
  do_it(args.win32json_api_directory, args.output_dir)
