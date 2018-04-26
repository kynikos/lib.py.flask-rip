# Maintainer: Dario Giovannetti <dev at dariogiovannetti dot net>

_name='flask-restinpeace'

pkgname="python-${_name}"
pkgver='1.2.0'
pkgrel=1
pkgdesc="Create Flask REST APIs in peace."
arch=('any')
url="https://github.com/kynikos/lib.py.flask-rip"
license=('MIT')
depends=('python-flask-marshmallow' 'python-apispec')
makedepends=('python-setuptools')
source=("https://files.pythonhosted.org/packages/source/${_name::1}/${_name}/${_name}-${pkgver}.tar.gz")
sha256sums=('c7644a27d3e7205dcc852860ba71359701ed44e0d23226f746e1fadadd540bd6')

package() {
    cd "${srcdir}/${_name}-${pkgver}"
    python setup.py install --root="${pkgdir}" --optimize=1
}
