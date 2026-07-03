<?php if ( ! defined( 'ABSPATH' ) ) exit; ?>
<!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo( 'charset' ); ?>">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="profile" href="https://gmpg.org/xfn/11">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="icon" type="image/png" sizes="32x32" href="https://trackdayfinder.co.uk/static/favicon-32.png">
<link rel="icon" type="image/png" sizes="192x192" href="https://trackdayfinder.co.uk/static/favicon-192.png">
<link rel="shortcut icon" href="https://trackdayfinder.co.uk/favicon.ico">
<?php wp_head(); ?>

<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-73PF9R6CT0"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-73PF9R6CT0');
</script>
</head>
<body <?php body_class(); ?>>

<header>
	<div class="brand-block">
		<a href="https://trackdayfinder.co.uk/" class="brand-link" aria-label="TrackdayFinder home">
			<img src="https://trackdayfinder.co.uk/static/logo-light.svg" alt="TrackdayFinder" class="brand-logo">
		</a>
		<span class="tagline">kindly provided by
			<a class="brand-gmracing" href="https://gmracing.co.uk" target="_blank" rel="noopener">GM<span class="brand-r">R</span>acing.co.uk</a>
		</span>
	</div>

	<nav class="top-nav">
		<?php if ( has_nav_menu( 'header_external' ) ) : ?>
			<?php wp_nav_menu( array(
				'theme_location' => 'header_external',
				'container'      => false,
				'items_wrap'     => '%3$s',
				'fallback_cb'    => false,
				'depth'          => 1,
			) ); ?>
		<?php else : ?>
			<a href="https://trackdayfinder.co.uk/">Trackday list</a>
			<a href="https://trackdayfinder.co.uk/map">Map</a>
			<a href="https://trackdayfinder.co.uk/calendar">Calendar</a>
			<a href="https://trackdayfinder.co.uk/circuits">Circuits</a>
			<a href="https://trackdayfinder.co.uk/organisers">Organisers</a>
			<a href="<?php echo esc_url( home_url( '/' ) ); ?>">Blog</a>
		<?php endif; ?>
	</nav>

	<span class="meta">
		<?php
		$tdf_count = (int) wp_count_posts()->publish;
		echo esc_html( sprintf( _n( '%d post', '%d posts', $tdf_count, 'trackdayfinder' ), $tdf_count ) );
		?>
	</span>
</header>

<nav class="crumbs">
	<a href="https://trackdayfinder.co.uk/">Home</a> &rsaquo;
	<a href="<?php echo esc_url( home_url( '/' ) ); ?>">Blog</a>
	<?php if ( is_singular() ) : ?>
		&rsaquo; <?php single_post_title(); ?>
	<?php elseif ( is_category() ) : ?>
		&rsaquo; <?php single_cat_title(); ?>
	<?php elseif ( is_tag() ) : ?>
		&rsaquo; #<?php single_tag_title(); ?>
	<?php elseif ( is_search() ) : ?>
		&rsaquo; Search: <?php echo esc_html( get_search_query() ); ?>
	<?php elseif ( is_archive() ) : ?>
		&rsaquo; <?php the_archive_title(); ?>
	<?php endif; ?>
</nav>

<main class="page">
