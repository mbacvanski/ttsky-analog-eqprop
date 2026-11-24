// Multi-terminal Dijkstra search over existing copper and an incremental four-layer grid.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <queue>
#include <vector>
#include <map>
#include <set>
#include <tuple>
using namespace std;
namespace {
int gx,gy,stride,step,nodes,offset;
struct Box {int l,x,y,X,Y,n,c;};
struct Join {int a,b; vector<int> path;};
vector<Box> geometry; vector<Join> result;
inline int point(int l,int x,int y){return l*stride+y*gx+x;}
int ceildiv(int v,int d){return v>=0?(v+d-1)/d:v/d;}
int floordiv(int v,int d){return v>=0?v/d:-((-v+d-1)/d);}
template<class F> void boxpoints(const Box& b,int r,F f){
 int floorx=max(0,ceildiv(b.x-r-offset,step)), topx=min(gx-1,floordiv(b.X+r-offset,step));
 int floory=max(0,ceildiv(b.y-r-offset,step)), topy=min(gy-1,floordiv(b.Y+r-offset,step));
 for(int y=floory;y<=topy;y++)for(int x=floorx;x<=topx;x++)f(x,y);
}
#ifdef LOCAL_ROUTING
constexpr int half[]{75,75,150,150};
constexpr int spacing[]{145,145,305,305};
#else
constexpr int half[]{230,230,270,270};
constexpr int spacing[]{185,185,430,430};
#endif
struct DSU {
 map<int,int> p;
 int root(int a){int b=p[a];return b==a?a:p[a]=root(b);}
 void join(int a,int b){p[root(a)]=root(b);}
};
}
extern "C" void setup(int pitch,int off,int nx,int ny,int *arr,int count){
 step=pitch;offset=off;gx=nx;gy=ny;stride=gx*gy;nodes=4*stride;geometry.clear();
 for(int i=0;i<count;i++)geometry.push_back({arr[i*7],arr[i*7+1],arr[i*7+2],arr[i*7+3],arr[i*7+4],arr[i*7+5],arr[i*7+6]});
}
extern "C" void add(int *a,int n){for(int i=0;i<n;i++)geometry.push_back({a[i*7],a[i*7+1],a[i*7+2],a[i*7+3],a[i*7+4],a[i*7+5],a[i*7+6]});}
extern "C" int route(int net,int *counts,int maxcounts){
 vector<uint8_t> block(nodes),via(3*stride);vector<int> at(nodes);map<int,vector<int>> sets;DSU dsu;
 for(const auto &b:geometry){
  if(b.l<4){
   if(b.n!=net){
    boxpoints(b,half[b.l]+spacing[b.l],[&](int x,int y){block[point(b.l,x,y)]=1;});
#ifdef LOCAL_ROUTING
    const int via_half[]={170,190,210,210};
    boxpoints(b,via_half[b.l]+spacing[b.l],[&](int x,int y){
     int p=y*gx+x;
     if(b.l>0)via[(b.l-1)*stride+p]=1;
     if(b.l<3)via[b.l*stride+p]=1;
    });
#endif
   }
   else if(b.c>0){sets[b.c];dsu.p[b.c]=b.c;}
  }else if(b.l==7){
   boxpoints(b,1620,[&](int x,int y){block[point(2,x,y)]=1;});
   boxpoints(b,650,[&](int x,int y){via[stride+y*gx+x]=1;via[2*stride+y*gx+x]=1;});
  }else if(b.l<7){
   int layer=b.l-4;boxpoints(b,layer==0?250:310,[&](int x,int y){via[layer*stride+y*gx+x]=1;});
  }
 }
 for(int l=0;l<4;l++)for(int y=0;y<gy;y++)for(int x=0;x<gx;x++)
  if(x<=1||x>=gx-2||y<=1||y>=gy-2)block[point(l,x,y)]=1;
 for(const auto &b:geometry)if(b.l<4&&b.n==net&&b.c>0)
  boxpoints(b,20,[&](int x,int y){int p=point(b.l,x,y); if(!block[p]&&!at[p]){at[p]=b.c;sets[b.c].push_back(p);}});
 result.clear();
 int k=0;
 for(const auto &[c,s]:sets){
  if(k+2<=maxcounts){counts[k++]=c;counts[k++]=s.size();}
  if(s.empty())return -c;
 }
 int remaining=sets.size();
 while(remaining>1){
  int start=-1;long smallest=__LONG_MAX__;
  map<int,long> size;
  for(auto &[c,s]:sets)size[dsu.root(c)]+=s.size();
  for(auto [c,n]:size)if(n<smallest){start=c;smallest=n;}
  // An admissible bound to the union of remaining conductor boxes.
  int tx=gx,ty=gy,tX=-1,tY=-1;
  for(auto &[c,s]:sets)if(dsu.root(c)!=start){for(int p:s){int t=p%stride,x=t%gx,y=t/gx;tx=min(x,tx);tX=max(x,tX);ty=min(y,ty);tY=max(y,tY);}}
  auto lower=[&](int p){int t=p%stride,x=t%gx,y=t/gx;return 8*(max({0,tx-x,x-tX})+max({0,ty-y,y-tY}));};
  using pairi=pair<int,int>;priority_queue<pairi,vector<pairi>,greater<pairi>> q;
  vector<int> dist(nodes,2147483647);vector<int8_t> prev(nodes,0);
  for(auto &[c,s]:sets)if(dsu.root(c)==start)for(int p:s){dist[p]=0;q.emplace(lower(p),p);}
  int found=-1,end=-1;
  int delta[]={-1,1,-gx,gx,-stride,stride};
  while(!q.empty()){
   auto [cost,p]=q.top();q.pop();
   if(cost!=dist[p]+lower(p))continue;
   if(at[p]&&dsu.root(at[p])!=start){found=at[p];end=p;break;}
   int l=p/stride;int ix=(p%stride)%gx,iy=(p%stride)/gx;
   for(int dir=0;dir<6;dir++){
    if((dir==0&&ix<2)||(dir==1&&ix>=gx-2)||(dir==2&&iy<2)||(dir==3&&iy>=gy-2)||(dir==4&&l==0)||(dir==5&&l==3))continue;
    int next=p+delta[dir];if(block[next])continue;
    if(dir==4||dir==5){int low=(dir==5?l:l-1);if(via[low*stride+p%stride])continue;}
    int weight=dir>=4?150:(((dir<2)==(l%2==0))?8:12);
    int nd=dist[p]+weight;
    if(nd>=dist[next])continue;
    dist[next]=nd;prev[next]=dir+1;q.emplace(nd+lower(next),next);
   }
  }
  if(end<0)return -100000-start;
  vector<int> path{end};
  while(prev[path.back()]){int p=path.back();path.push_back(p-delta[prev[p]-1]);}
  reverse(path.begin(),path.end());
  result.push_back({start,found,path});dsu.join(start,found);
  for(int p:path)if(!at[p]){at[p]=found;sets[found].push_back(p);}
  remaining--;
 }
 return result.size();
}
extern "C" int path_length(int k){return result[k].path.size();}
extern "C" void path_read(int k,int* data){copy(result[k].path.begin(),result[k].path.end(),data);}
