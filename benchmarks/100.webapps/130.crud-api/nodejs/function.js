const nosql = require('./nosql');

const nosqlClient = nosql.nosql.get_instance();
const nosqlTableName = "shopping_cart";

async function addProduct(cartId, productId, productName, price, quantity) {
  await nosqlClient.insert(
    nosqlTableName,
    ["cart_id", cartId],
    ["product_id", productId],
    { price: price, quantity: quantity, name: productName }
  );
}

async function getProducts(cartId, productId) {
  return await nosqlClient.get(
    nosqlTableName, 
    ["cart_id", cartId], 
    ["product_id", productId]
  );
}

async function queryProducts(cartId) {
  const res = await nosqlClient.query(
    nosqlTableName,
    ["cart_id", cartId],
    "product_id"
  );

  const products = [];
  let priceSum = 0;
  let quantitySum = 0;

  for (const product of res) {
    products.push(product.name);
    priceSum += product.price;
    quantitySum += product.quantity;
  }

  const avgPrice = quantitySum > 0 ? priceSum / quantitySum : 0.0;

  return {
    products: products,
    total_cost: priceSum,
    avg_price: avgPrice
  };
}

exports.handler = async function(event) {
  const results = [];

  for (const request of event.requests) {
    const route = request.route;
    const body = request.body;
    let res;

    if (route === "PUT /cart") {
      await addProduct(
        body.cart,
        body.product_id,
        body.name,
        body.price,
        body.quantity
      );
      res = {};
    } else if (route === "GET /cart/{id}") {
      res = await getProducts(body.cart, request.path.id);
    } else if (route === "GET /cart") {
      res = await queryProducts(body.cart);
    } else {
      throw new Error(`Unknown request route: ${route}`);
    }

    results.push(res);
  }

  return { result: results };
};
