# ruff: noqa  (scratch spike script, not product code)
import zipfile, sys
sys.path.insert(0, ".")
from build_fx import NS, HDR
import build_fx
F = [
 'SUM(A1:A8)','AVERAGE(A1:A8)','MIN(A1:A8)','MAX(A1:A8)','COUNT(A1:A8)','COUNTA(B1:B8)','COUNTBLANK(B1:B8)','ABS(-5)',
 'ROUND(2.567,2)','ROUNDUP(2.561,1)','ROUNDDOWN(2.569,1)','INT(-2.5)','MOD(-7,3)','IF(A1>2,"y","n")','IFS(A1>5,"a",A1>2,"b",TRUE,"c")',
 'IFERROR(1/0,"err")','AND(TRUE,FALSE)','OR(TRUE,FALSE)','NOT(TRUE)','LEN(B1)','LEFT(B2,3)','RIGHT(B2,2)','MID(B3,2,3)','TRIM(B5)',
 'UPPER(B1)','LOWER(B2)','CONCAT(B1,"-",B2)','CONCATENATE(B1,"-",B2)','VALUE("12.5")','ISNUMBER(A1)','ISTEXT(B1)','ISBLANK(B6)','ISERROR(1/0)',
 'SUMIF(A1:A8,">2")','SUMIFS(C1:C8,A1:A8,">2",A1:A8,"<9")','COUNTIF(B1:B8,"apple")','COUNTIFS(A1:A8,">1",C1:C8,"<60")','AVERAGEIF(A1:A8,">2")',
 'VLOOKUP(4,A1:C8,3,FALSE)','HLOOKUP(3,A1:C2,2,FALSE)','INDEX(C1:C8,3)','MATCH(5,A1:A8,0)','XLOOKUP(5,A1:A8,C1:C8)',
 'DATE(2024,2,29)','YEAR(D1)','MONTH(D1)','DAY(D1)','SUBSTITUTE(B1,"p","P")','FIND("a",B1)','SEARCH("A",B1)',
 'TEXT(1234.5,"#,##0.00")','TEXT(D1,"yyyy-mm-dd")','TEXT(0.256,"0.0%")','SUMPRODUCT(A1:A8,C1:C8)','ROW(A5)','COLUMN(C1)',
 '1/0','"a"&1','2^10','-2^2','10%','"10"+5','A1&""','TRUE+1','MEDIAN(A1:A8)','STDEV(A1:A8)','LARGE(A1:A8,2)','SMALL(A1:A8,2)',
 'POWER(2,3)','SQRT(16)','SQRT(-1)','PI()','EXACT("a","A")','"a"="A"','"a"<"B"','WEEKDAY(D1)','EDATE(D1,1)','EOMONTH(D1,0)',
 'CHOOSE(2,"a","b","c")','SWITCH(2,1,"a",2,"b")','REPT("ab",3)','PROPER("hello world")','COUNTIF(B1:B8,"a*")','ROUND(-2.5,0)','ROUND(2.5,0)',
 '0.1+0.2=0.3','(0.1+0.2)-0.3','1E+308*10','VALUE("abc")','TRUE&"x"','N(TRUE)','VLOOKUP(5,A1:C8,3,TRUE)','NETWORKDAYS(D1,D2)',
 'RAND()>=0','TODAY()>0','SUM(A1:A8,"3")','SUM("3",1)','AVERAGE(B1:B2)','MAX(B1:B8)','IF("x",1,2)','LEN(12345)','DATEDIF(D1,D2,"d")',
 'TEXTJOIN(",",TRUE,B1:B4)','UNIQUE(A1:A8)','SUM(FILTER(A1:A8,A1:A8>2))','LET(x,2,x*3)','SEQUENCE(2)',
]
A=[3,1,4,1,5,9,2,6]; B=["apple","Banana","cherry","apple","  trim me  ","","Date","x"]; C=[10,20,30,40,50,60,70,80]; D=[45292,45323,45352]
def build(path):
    rows=[]
    for i in range(1,max(len(A),len(F))+1):
        cells=[]
        if i<=8:
            cells.append(f'<c r="A{i}"><v>{A[i-1]}</v></c>')
            if B[i-1]: cells.append(f'<c r="B{i}" t="inlineStr"><is><t xml:space="preserve">{B[i-1]}</t></is></c>')
            cells.append(f'<c r="C{i}"><v>{C[i-1]}</v></c>')
        if i<=3: cells.append(f'<c r="D{i}"><v>{D[i-1]}</v></c>')
        f=F[i-1].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") if i<=len(F) else None
        if f: cells.append(f'<c r="F{i}"><f>{f}</f></c>')
        rows.append(f'<row r="{i}">{"".join(cells)}</row>')
    sheet=HDR+f'<worksheet {NS}><sheetData>{"".join(rows)}</sheetData></worksheet>'
    build_fx.build("fx/_t2.xlsx", extras=False)
    src=zipfile.ZipFile("fx/_t2.xlsx")
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            z.writestr(n, sheet if n=="xl/worksheets/sheet1.xml" else src.read(n))
build("fx/formulas.xlsx"); print(len(F),"formulas")
