Make a Binary Ninja type library with Windows types.

### How

* Windows SDK contains type information in headers
* https://github.com/microsoft/win32metadata scrapes Windows SDK headers and produces C# files
* https://github.com/marlersoft/win32jsongen converts the C# files into .json
* https://github.com/marlersoft/win32json stores the output from win32jsongen (~100mb)
* (this project) converts the json into a Binary Ninja type library (~6mb)

### Running

Ensure Binary Ninja is in your python path:

```
$ env | grep PYTHONPATH
PYTHONPATH=/Applications/Binary Ninja.app/Contents/Resources/python
```

First argument is location of .json files from win32json, second argument is output path:

```
$ ./main.py ../win32json/api/ ./output.bntl
```

