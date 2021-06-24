#!/usr/bin/env python3
import json
import codecs
import sys
import logging
import binaryninja
from argparse import ArgumentParser
from pathlib import Path

typelib = binaryninja.typelibrary.TypeLibrary.new(binaryninja.Architecture["x86_64"], "Win32")
arch = binaryninja.Architecture["x86_64"]
api_namespaces = {}

def kind_to_bn_type(kind):
  if kind["Kind"] == "Native":
    return get_bn_type_from_name(kind["Name"])
  if kind["Kind"] == "ApiRef":
    return typelib.get_named_type(kind["Name"])

def get_bn_type_from_name(name):
  if name == "Byte":
    return binaryninja.types.Type.int(1, sign=False)
  elif name == "SByte":
    return binaryninja.types.Type.int(1)
  elif name == "Char":
    return binaryninja.types.Type.char()
  elif name == "UInt16":
    return binaryninja.types.Type.int(2, sign=False)
  elif name == "Int16":
    return binaryninja.types.Type.int(2)
  elif name == "Int64":
    return binaryninja.types.Type.int(8)
  elif name == "UInt32":
    return binaryninja.types.Type.int(4, sign=False)
  elif name == "UInt64":
    return binaryninja.types.Type.int(8, sign=False)
  elif name == "Int32":
    return binaryninja.types.Type.int(4)
  elif name == "Single":
    return binaryninja.types.Type.float(4)
  elif name == "Double":
    return binaryninja.types.Type.float(8)
  elif name == "UIntPtr":
    return binaryninja.types.Type.pointer(arch, binaryninja.types.Type.int(8, sign=False))
  elif name == "IntPtr":
    return binaryninja.types.Type.pointer(arch, binaryninja.types.Type.int(8, sign=True))
  elif name == "Void":
    return binaryninja.types.Type.void()
  elif name == "Boolean":
    return binaryninja.types.Type.bool()
  elif name == "Guid":
    #FIXME
    return binaryninja.types.Type.void()
  else:
    print(f"Unhandled Native Type: {name}")
    sys.exit(-1)

def handle_json_type(t):
  if t["Kind"] == "Native":
    return get_bn_type_from_name(t["Name"])
  if t["Kind"] == "PointerTo":
    return binaryninja.types.Type.pointer(arch, handle_json_type(t["Child"]))
  if t["Kind"] == "Array":
    if t["Shape"]:
      return binaryninja.types.Type.array(handle_json_type(t["Child"]), int(t["Shape"]["Size"]))
    else:
      return binaryninja.types.Type.pointer(arch, handle_json_type(t["Child"]))
  if t["Kind"] == "ApiRef":
#    found_type = typelib.get_named_type(t["Name"])
#    if found_type:
#      return found_type
#    else:
    return binaryninja.types.Type.named_type(binaryninja.types.NamedTypeReference(name=t["Name"]))
  if t["Kind"] == "Struct":
    for nested_type in t["NestedTypes"]:
      typelib.add_named_type(nested_type["Name"], handle_json_type(nested_type))
    new_struct = binaryninja.types.Structure()
    for field in t["Fields"]:
      child_type = handle_json_type(field["Type"])
      new_struct.append(child_type, field["Name"])
    return binaryninja.types.Type.structure_type(new_struct)
  if t["Kind"] == "LPArray":
    return binaryninja.types.Type.pointer(arch, handle_json_type(t["Child"]))
  if t["Kind"] == "Union":
    for nested_type in t["NestedTypes"]:
      typelib.add_named_type(nested_type["Name"], handle_json_type(nested_type))
    new_union = binaryninja.types.Structure()
    new_union.type = binaryninja.enums.StructureType.UnionStructureType
    for field in t["Fields"]:
      child_type = handle_json_type(field["Type"])
      new_union.append(child_type, field["Name"])
    return binaryninja.types.Type.structure_type(new_union)
  if t["Kind"] == "MissingClrType":
    return binaryninja.types.Type.void()
  else:
    print(f"Unhandled type: {t}")
    sys.exit(0)

def create_bn_type_from_json(t):
  if t["Kind"] == "NativeTypedef":
    new_typedef = handle_json_type(t["Def"])
    real_new_type = typelib.add_named_type(t["Name"], new_typedef)
  elif t["Kind"] == "Enum":
    new_enum = binaryninja.types.Enumeration()
    for member in t["Values"]:
      new_enum.append(member["Name"], int(member["Value"]))
    real_new_type = binaryninja.types.Type.named_type_from_type(t["Name"], binaryninja.types.Type.enumeration_type(arch,new_enum))
    typelib.add_named_type(t["Name"], real_new_type)
  elif t["Kind"] == "Struct":
    real_new_type = handle_json_type(t)
    typelib.add_named_type(t["Name"], real_new_type)
  elif t["Kind"] == "FunctionPointer":
    ret_type = handle_json_type(t["ReturnType"])
    param_list = []
    for param in t["Params"]:
      new_param = handle_json_type(param["Type"])
      real_new_param = binaryninja.types.FunctionParameter(new_param, param["Name"])
      param_list.append(real_new_param)
    typelib.add_named_type(t["Name"], binaryninja.types.Type.pointer(arch, binaryninja.types.Type.function(ret_type, param_list)))
  elif t["Kind"] == "Com":
    new_struct = binaryninja.types.Structure()
    for method in t["Methods"]:
      ret_type = handle_json_type(method["ReturnType"])
      param_list = []
      for param in method["Params"]:
        new_param = handle_json_type(param["Type"])
        real_new_param = binaryninja.types.FunctionParameter(new_param, param["Name"])
        param_list.append(real_new_param)
      new_func = binaryninja.types.Type.function(ret_type, param_list)
      new_struct.append(binaryninja.types.Type.pointer(arch, new_func), method["Name"])
    typelib.add_named_type(t["Name"], binaryninja.types.Type.structure_type(new_struct))
  elif t["Kind"] == "ComClassID":
    return None
  elif t["Kind"] == "Union":
    real_new_type = handle_json_type(t)
    typelib.add_named_type(t["Name"], real_new_type)
    return None
  else:
    print(f"Found unknown type kind: {t['Kind']}")


def do_it(in_dir, out_dir):
  p = Path(in_dir)

  files = p.glob("*.json")

  for file in files:
    api_namespaces[file.stem] = json.load(codecs.open(file, "r", "utf-8-sig"))

  logging.info("Making a bunch of types...")
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
      ret_type = handle_json_type(f["ReturnType"])
      param_list = []
      for param in f["Params"]:
        new_param = handle_json_type(param["Type"])
        real_new_param = binaryninja.types.FunctionParameter(new_param, param["Name"])
        param_list.append(real_new_param)
      new_func = binaryninja.types.Type.function(ret_type, param_list)
      typelib.add_named_object(f["Name"], new_func)
      func_count+=1

  typelib.finalize()
  typelib.write_to_file(out_dir)

if __name__ == "__main__":
  _args = ArgumentParser(description='Build a typelib from win32json project')
  _args.add_argument("win32json_api_directory")
  _args.add_argument("output_dir")
  _args.add_argument("-v", action="count", help="Increase logging verbosity. Can specify multiple times.")
  args = _args.parse_args()
  if args.v != None:
    logging.basicConfig(level=max(30-(args.v * 10), 0))
  do_it(args.win32json_api_directory, args.output_dir)