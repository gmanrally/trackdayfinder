<?php
/**
 * TrackdayFinder theme bootstrap.
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

if ( ! function_exists( 'tdf_setup' ) ) :
	function tdf_setup() {
		add_theme_support( 'title-tag' );
		add_theme_support( 'post-thumbnails' );
		add_theme_support( 'automatic-feed-links' );
		add_theme_support( 'html5', array( 'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'style', 'script' ) );
		add_theme_support( 'responsive-embeds' );

		register_nav_menus( array(
			'header_external' => __( 'Header — links back to the main site', 'trackdayfinder' ),
		) );
	}
endif;
add_action( 'after_setup_theme', 'tdf_setup' );

function tdf_enqueue_assets() {
	wp_enqueue_style(
		'tdf-inter',
		'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap',
		array(),
		null
	);
	wp_enqueue_style(
		'tdf-theme',
		get_stylesheet_uri(),
		array( 'tdf-inter' ),
		wp_get_theme()->get( 'Version' )
	);
}
add_action( 'wp_enqueue_scripts', 'tdf_enqueue_assets' );

/**
 * Default nav items linking back to the main site — used when the
 * 'header_external' menu hasn't been configured in WP admin yet.
 */
function tdf_default_nav_items() {
	return array(
		'Home'       => 'https://trackdayfinder.co.uk/',
		'Map'        => 'https://trackdayfinder.co.uk/map',
		'Calendar'   => 'https://trackdayfinder.co.uk/calendar',
		'Circuits'   => 'https://trackdayfinder.co.uk/circuits',
		'Organisers' => 'https://trackdayfinder.co.uk/organisers',
		'Blog'       => home_url( '/' ),
	);
}

/**
 * Render the header nav. Prefer the WP-configured menu, fall back to
 * the hard-coded defaults so the theme works the moment it's activated.
 */
function tdf_render_nav() {
	if ( has_nav_menu( 'header_external' ) ) {
		wp_nav_menu( array(
			'theme_location' => 'header_external',
			'container'      => false,
			'menu_class'     => 'tdf-nav',
			'fallback_cb'    => false,
			'depth'          => 1,
		) );
		return;
	}
	echo '<nav class="tdf-nav">';
	foreach ( tdf_default_nav_items() as $label => $url ) {
		printf(
			'<a href="%1$s">%2$s</a>',
			esc_url( $url ),
			esc_html( $label )
		);
	}
	echo '</nav>';
}

/**
 * Inline-render the brand SVG so the theme is self-contained. Mirrors
 * the markup of /static/logo-light.svg on the main site.
 */
function tdf_brand_svg() {
	?>
	<svg class="tdf-brand-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 60" role="img" aria-label="TrackdayFinder">
		<text x="0" y="42" font-family="Inter, system-ui, sans-serif" font-weight="800" font-size="36" letter-spacing="-0.02em" fill="#ffffff">Trackday<tspan fill="#dc2626">Finder</tspan><tspan fill="#94a3b8" font-size="18">.co.uk</tspan></text>
	</svg>
	<?php
}

/**
 * Excerpt cap and read-more link styling.
 */
function tdf_excerpt_more( $more ) {
	return '…';
}
add_filter( 'excerpt_more', 'tdf_excerpt_more' );
